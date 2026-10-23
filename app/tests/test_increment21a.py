import hashlib
import hmac
import sqlite3
from urllib.parse import urlparse, parse_qs
import pytest
from services.crypto import encrypt_secret, decrypt_secret
from services.security_migration import migrate_security
from services.oauth_pending import begin, consume
from services.local_tls import ensure_local_tls
from database.migrations import ensure_database

def legacy(text,key):
    nonce=b'N'*16
    data=text.encode()
    stream=b''.join(hmac.new(key,nonce+i.to_bytes(4,'big'),hashlib.sha256).digest() for i in range((len(data)+31)//32))
    cipher=bytes(a^b for a,b in zip(data,stream))
    return (nonce+hmac.new(key,nonce+cipher,hashlib.sha256).digest()+cipher).hex()

def setup(tmp_path):
    db=tmp_path/'test.db'; ensure_database(db)
    key=tmp_path/'key'; key.write_bytes(b'K'*32)
    return db,key

def test_legacy_migration_backup_idempotence(tmp_path):
    db,key=setup(tmp_path)
    old=legacy('secret',key.read_bytes())
    with sqlite3.connect(db) as c: c.execute('UPDATE ml_credentials SET client_secret_encrypted=?',(old,))
    migrate_security(db,key)
    with sqlite3.connect(db) as c:
        value=c.execute('SELECT client_secret_encrypted FROM ml_credentials').fetchone()[0]
    assert value.startswith('fernet:v1:') and decrypt_secret(value,key)=='secret'
    backup=next((tmp_path/'backups').glob('pre*'))
    with sqlite3.connect(backup/'database.db') as c:
        assert c.execute('SELECT client_secret_encrypted FROM ml_credentials').fetchone()[0]==old
    assert (backup/'master.key').read_bytes()==key.read_bytes()==b'K'*32
    migrate_security(db,key)
    assert len(list((tmp_path/'backups').glob('pre*')))==1

def test_corruption_rolls_back(tmp_path):
    db,key=setup(tmp_path)
    with sqlite3.connect(db) as c:
        c.execute('UPDATE ml_credentials SET client_secret_encrypted=?,access_token_encrypted=?',(legacy('good',key.read_bytes()),'broken'))
    with pytest.raises(ValueError): migrate_security(db,key)
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT access_token_encrypted FROM ml_credentials').fetchone()[0]=='broken'
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='security_versions'").fetchone()

def test_pkce_restart_binding_expiry_and_replay(tmp_path):
    db,key=setup(tmp_path); migrate_security(db,key)
    with sqlite3.connect(db) as c:
        url=begin(c,'123','https://127.0.0.1:5000/ml/callback','browser',key,now=100)
    params=parse_qs(urlparse(url).query); state=params['state'][0]
    with sqlite3.connect(db) as c:
        raw=c.execute('SELECT * FROM oauth_pending').fetchone()
        assert state not in raw and 'fernet:v1:' in raw[2]
        with pytest.raises(ValueError): consume(c,state,'other',key,now=101)
        verifier,uri=consume(c,state,'browser',key,now=102)
        import base64
        assert base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')==params['code_challenge'][0]
    with sqlite3.connect(db) as c:
        with pytest.raises(ValueError): consume(c,state,'browser',key,now=103)
        url=begin(c,'123',uri,'browser',key,now=200)
        with pytest.raises(ValueError): consume(c,parse_qs(urlparse(url).query)['state'][0],'browser',key,now=800)

def test_missing_key_never_replaced(tmp_path):
    key=tmp_path/'missing'
    with pytest.raises(ValueError): decrypt_secret('gAAAAinvalid',key)
    assert not key.exists()

def test_tls_san_and_permissions(tmp_path):
    from cryptography import x509
    cert,key=ensure_local_tls(tmp_path)
    loaded=x509.load_pem_x509_certificate(open(cert,'rb').read())
    assert 'localhost' in loaded.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    assert __import__('os').name == 'nt' or __import__('pathlib').Path(key).stat().st_mode & 0o777==0o600
    assert ensure_local_tls(tmp_path)==(cert,key)

def test_local_prepare_callback_and_restart(tmp_path):
    from web.app import create_app
    db,key=setup(tmp_path)
    config={'TESTING':True,'DB_PATH':db,'KEY_FILE':key,'SECRET_KEY':'test-only'}
    app=create_app(config)
    with sqlite3.connect(db) as c: c.execute("UPDATE ml_credentials SET client_id='123'")
    client=app.test_client()
    assert client.post('/ml/connect',base_url='https://127.0.0.1:5000').status_code==403
    assert client.post('/ml/prepare',base_url='https://127.0.0.1:5000').status_code==403
    response=client.post('/ml/prepare',base_url='https://127.0.0.1:5000',headers={'Origin':'https://127.0.0.1:5000'})
    assert response.status_code==200
    assert response.headers['Cache-Control']=='no-store'
    state=parse_qs(urlparse(response.json['authorization_url']).query)['state'][0]
    cookie=client.get_cookie('session',domain='127.0.0.1')
    restarted=create_app(config).test_client()
    restarted.set_cookie('session',cookie.value,domain='127.0.0.1')
    callback='/ml/callback?state='+state+'&code=synthetic-code'
    assert restarted.get(callback,base_url='https://127.0.0.1:5000').status_code==200
    assert restarted.get(callback,base_url='https://127.0.0.1:5000').status_code==400
