"""Integration tests use disposable databases on an explicitly configured local PostgreSQL."""
import json
import os
from pathlib import Path
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import pytest
from werkzeug.security import generate_password_hash
from database.connection import get_db
from database.migrations import ensure_database
from services.importer import execute_import
from services.parser import parse_xlsx
from models.sales import get_sales_summary
from services.crypto import DEFAULT_KEY_FILE, encrypt_secret, decrypt_secret
from web.app import create_app

ORIGIN='https://painel.example.test'

def test_business_migration_preserves_source_and_refuses_merge(pg_url,tmp_path):
    import importlib.util
    import hashlib
    script=Path(__file__).resolve().parents[2]/'scripts'/'migrate_business_data.py'
    spec=importlib.util.spec_from_file_location('business_migration',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source=tmp_path/'source.db'
    ensure_database(source)
    from services.security_migration import migrate_security
    migrate_security(source)
    before=hashlib.sha256(source.read_bytes()).digest()
    counts=module.migrate(source,pg_url)
    assert counts['settings']==1 and counts['sales']==0
    assert hashlib.sha256(source.read_bytes()).digest()==before
    with get_db(pg_url) as conn:
        conn.execute("UPDATE ml_credentials SET client_id='already-configured'")
    with pytest.raises(ValueError): module.migrate(source,pg_url)
    with get_db(pg_url) as conn:
        assert conn.execute('SELECT client_id FROM ml_credentials').fetchone()[0]=='already-configured'

@pytest.fixture
def pg_url():
    url=os.environ.get('TEST_POSTGRES_URL')
    if not url: pytest.skip('Requer PostgreSQL local em TEST_POSTGRES_URL.')
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    info=conninfo_to_dict(url)
    if info.get('host') not in ('localhost','127.0.0.1'): pytest.fail('Testes destrutivos permitidos somente em loopback.')
    name='bt_test_'+uuid.uuid4().hex
    with psycopg.connect(url,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    info['dbname']=name
    # Preserve URI format so production adapter selection is exercised.
    from urllib.parse import urlsplit,urlunsplit
    parts=urlsplit(url)
    target=urlunsplit((parts.scheme,parts.netloc,'/'+name,parts.query,''))
    try:
        ensure_database(target)
        yield target
    finally:
        with psycopg.connect(url,autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))

@pytest.fixture
def cloud(pg_url,monkeypatch):
    monkeypatch.setenv('BASETRILHEIROS_MASTER_SECRET','synthetic-cloud-master-secret-'+'x'*32)
    config={'TESTING':True,'CLOUD_MODE':True,'PUBLIC_BASE_URL':ORIGIN,'DATABASE_URL':pg_url,
        'BASETRILHEIROS_SECRET_KEY':'synthetic-session-secret-'+'x'*32,
        'ADMIN_USERNAME':'owner','ADMIN_PASSWORD_HASH':generate_password_hash('synthetic-owner-password',method='pbkdf2:sha256:600000'),
        'ML_TEST_TRANSPORT':Mock()}
    app=create_app(config)
    return app,config,pg_url

def token(client):
    page=client.get('/login',base_url=ORIGIN)
    return re.search(rb'name="csrf_token" value="([^"]+)"',page.data).group(1).decode()

def login(client):
    t=token(client)
    response=client.post('/login',base_url=ORIGIN,headers={'Origin':ORIGIN},data={'csrf_token':t,'username':'owner','password':'synthetic-owner-password'})
    assert response.status_code==303
    with client.session_transaction(base_url=ORIGIN) as s: return s['ml_setup_csrf']

def test_postgres_import_ids_constraints_and_idempotent_schema(pg_url):
    ensure_database(pg_url)
    parsed=parse_xlsx(Path(__file__).parent/'fixtures/sample.xlsx',2026)
    with get_db(pg_url) as conn:
        result=execute_import(conn,parsed,'synthetic.xlsx','xlsx','synthetic')
        assert result['import_id']>0 and result['novas_vendas']==10
        assert get_sales_summary(conn)['em_revisao']['centavos']==5670
    with get_db(pg_url) as conn:
        result=execute_import(conn,parsed,'synthetic.xlsx','xlsx','synthetic')
        assert result['duplicadas_ignoradas']==10
        assert conn.execute('SELECT count(*) FROM sales').fetchone()[0]==10
    with pytest.raises(Exception):
        with get_db(pg_url) as conn:
            conn.execute("INSERT INTO monitored_products(url,titulo,preco_alvo_centavos) VALUES ('url','one',1)")
            conn.execute("INSERT INTO monitored_products(url,titulo,preco_alvo_centavos) VALUES ('url','two',2)")
    with get_db(pg_url) as conn: assert conn.execute('SELECT count(*) FROM monitored_products').fetchone()[0]==0

def test_hosted_login_protects_all_data_and_checks_origin(cloud):
    app,_,_=cloud;c=app.test_client()
    assert c.get('/healthz').json=={'status':'ok'}
    for path in ('/','/sales','/mercado-livre','/ml/callback?code=synthetic','/diagnostics'):
        assert c.get(path,base_url=ORIGIN).status_code==303
    assert c.get('/sales',base_url='https://foreign.invalid').status_code==400
    assert c.post('/login',base_url=ORIGIN).status_code==403
    t=token(c)
    assert c.post('/login',base_url=ORIGIN,headers={'Origin':'https://foreign.invalid'},data={'csrf_token':t}).status_code==403
    t=login(c)
    assert c.get('/sales',base_url=ORIGIN).status_code==200
    assert c.get('/__local/health',base_url=ORIGIN).status_code==404
    assert c.get('/ml/return',base_url=ORIGIN).status_code==404
    assert c.post('/parameters/save',base_url=ORIGIN).status_code==403
    assert c.post('/logout',base_url=ORIGIN,headers={'Origin':ORIGIN},data={'csrf_token':t}).status_code==303
    assert c.get('/sales',base_url=ORIGIN).status_code==303

def test_login_throttle_is_persistent(cloud):
    app,config,url=cloud;c=app.test_client();t=token(c)
    for _ in range(10):
        assert c.post('/login',base_url=ORIGIN,data={'csrf_token':t,'username':'owner','password':'wrong'}).status_code==400
    other=create_app(config).test_client();t=token(other)
    assert other.post('/login',base_url=ORIGIN,data={'csrf_token':t,'username':'owner','password':'synthetic-owner-password'}).status_code==429

def test_cloud_native_oauth_callback_and_encrypted_token_storage(cloud):
    app,config,url=cloud;c=app.test_client();t=login(c)
    assert c.post('/mercado-livre/save',base_url=ORIGIN,headers={'Origin':ORIGIN},data={
        'csrf_token':t,'client_id':'123','client_secret':'synthetic-provider-secret','redirect_uri':'https://untrusted.example/ml/callback'}).status_code==302
    with get_db(url) as conn:
        row=conn.execute('SELECT * FROM ml_credentials WHERE id=1').fetchone()
        assert row['redirect_uri']==ORIGIN+'/ml/callback'
        assert 'synthetic-provider-secret' not in row['client_secret_encrypted']
    config['ML_TEST_TRANSPORT'].exchange.return_value={'access_token':'synthetic-access','refresh_token':'synthetic-refresh','expires_in':3600,'token_type':'bearer'}
    from urllib.parse import parse_qs,urlsplit
    result=c.post('/ml/connect',base_url=ORIGIN,headers={'Origin':ORIGIN},data={'csrf_token':t})
    q=parse_qs(urlsplit(result.location).query)
    assert q['redirect_uri']==[ORIGIN+'/ml/callback']
    state=q['state'][0]
    # New application instance retains signed browser session and durable pending state.
    again=create_app(config).test_client()
    cookie=c.get_cookie('__Host-basetrilheiros',domain='painel.example.test')
    again.set_cookie('__Host-basetrilheiros',cookie.value,domain='painel.example.test')
    response=again.get('/ml/callback?state='+state+'&code=synthetic-code',base_url=ORIGIN)
    assert response.status_code==303 and 'code=' not in response.location
    assert config['ML_TEST_TRANSPORT'].exchange.call_count==1
    again.get('/ml/callback?state='+state+'&code=synthetic-code',base_url=ORIGIN)
    assert config['ML_TEST_TRANSPORT'].exchange.call_count==1
    with get_db(url) as conn:
        assert decrypt_secret(conn.execute('SELECT access_token_encrypted FROM ml_credentials').fetchone()[0])=='synthetic-access'

def test_hosted_signed_import_and_private_backup(cloud):
    app,_,url=cloud;c=app.test_client();t=login(c)
    pasted='LOJA_TESTE\tR$10,001 unidade\tR$1,00Venda direta: 10%\tEM REVISÃO\n29/set#9001\nProduto fictícioCategoria: Testes'
    prev=c.post('/sales/preview-paste',base_url=ORIGIN,headers={'Origin':ORIGIN},data={'csrf_token':t,'ano':'2026','pasted_text':pasted}).json
    assert prev['source_info']['signature']
    tampered=json.loads(json.dumps(prev['preview']));tampered['registros'][0]['comissao_centavos']=9999999
    c.post('/sales/confirm-import',base_url=ORIGIN,data={'csrf_token':t,'preview_data':json.dumps(tampered),'source_info':json.dumps(prev['source_info'])})
    with get_db(url) as conn: assert conn.execute('SELECT count(*) FROM sales').fetchone()[0]==0
    c.post('/sales/confirm-import',base_url=ORIGIN,data={'csrf_token':t,'preview_data':json.dumps(prev['preview']),'source_info':json.dumps(prev['source_info'])})
    with get_db(url) as conn: assert conn.execute('SELECT count(*) FROM sales').fetchone()[0]==1
    diagnostics=c.get('/diagnostics',base_url=ORIGIN)
    assert diagnostics.status_code==200 and url.encode() not in diagnostics.data
    backup=c.post('/diagnostics/backup',base_url=ORIGIN,data={'csrf_token':t})
    assert backup.status_code==200 and backup.json['tables']['sales'][0]['comissao_centavos']==100
    assert 'attachment' in backup.headers['Content-Disposition']

def test_postgres_refresh_rotation_once_across_threads(cloud,monkeypatch):
    _,_,url=cloud
    from services.ml_live import access_token
    with get_db(url) as conn:
        conn.execute("UPDATE ml_credentials SET client_id='123',client_secret_encrypted=?,access_token_encrypted=?,refresh_token_encrypted=?,status='autorizado',token_expires_at='2020-01-01'",
            (encrypt_secret('synthetic-secret'),encrypt_secret('old-access'),encrypt_secret('old-refresh')))
    refresh=Mock(return_value={'access_token':'new-access','refresh_token':'new-refresh','expires_in':3600,'token_type':'bearer'})
    monkeypatch.setattr('services.ml_live.ml_auth.refresh_token',refresh)
    with ThreadPoolExecutor(max_workers=2) as workers:
        values=list(workers.map(lambda _:access_token(url,DEFAULT_KEY_FILE),range(2)))
    assert values==['new-access','new-access'] and refresh.call_count==1

def test_cloud_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv('BASETRILHEIROS_MASTER_SECRET',raising=False)
    with pytest.raises(RuntimeError): create_app({'TESTING':True,'CLOUD_MODE':True,'PUBLIC_BASE_URL':ORIGIN,'DATABASE_URL':'postgresql://localhost/test'})
