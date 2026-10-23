import re
import sqlite3
import pytest
from web.app import create_app
from services.crypto import decrypt_secret

@pytest.fixture
def setup_panel(tmp_path):
    db=tmp_path/'panel.db'; key=tmp_path/'key'
    app=create_app({'TESTING':True,'DB_PATH':db,'KEY_FILE':key,'SECRET_KEY':'testing-only'})
    return app.test_client(),db,key

def csrf(client):
    response=client.get('/mercado-livre',base_url='https://localhost')
    assert response.status_code==200
    assert response.headers['Cache-Control']=='no-store'
    return re.search(rb'name="csrf_token" value="([^"]+)"',response.data).group(1).decode()

def test_secret_encrypted_never_rendered_and_blank_preserves(setup_panel):
    client,db,key=setup_panel; token=csrf(client)
    data={'csrf_token':token,'client_id':'123456','client_secret':'TEST-SECRET-DO-NOT-DISPLAY'}
    response=client.post('/mercado-livre/save',data=data,base_url='https://localhost',follow_redirects=True)
    assert response.status_code==200
    assert data['client_secret'].encode() not in response.data
    with sqlite3.connect(db) as c:
        encrypted=c.execute('SELECT client_secret_encrypted FROM ml_credentials').fetchone()[0]
        assert encrypted.startswith('fernet:v1:')
        assert decrypt_secret(encrypted,key)==data['client_secret']
    data['client_secret']=''
    assert client.post('/mercado-livre/save',data=data,base_url='https://localhost').status_code==302
    with sqlite3.connect(db) as c:assert c.execute('SELECT client_secret_encrypted FROM ml_credentials').fetchone()[0]==encrypted
    data['client_id']='999'
    assert client.post('/mercado-livre/save',data=data,base_url='https://localhost').status_code==400
    with sqlite3.connect(db) as c:assert c.execute('SELECT client_id FROM ml_credentials').fetchone()[0]=='123456'

def test_csrf_and_invalid_id(setup_panel):
    client,db,key=setup_panel
    assert client.post('/mercado-livre/save',base_url='https://localhost').status_code==400
    assert client.post('/mercado-livre/simulate',base_url='https://localhost').status_code==400
    token=csrf(client)
    assert client.post('/mercado-livre/save',base_url='https://localhost',data={'csrf_token':token,'client_id':'not-an-id','client_secret':'test'}).status_code==400
    assert not key.exists()

def test_simulation_no_changes_or_credentials_needed(setup_panel):
    client,db,key=setup_panel;token=csrf(client)
    def snapshot():
        with sqlite3.connect(db) as c:
            tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {t:c.execute('SELECT * FROM "'+t+'"').fetchall() for t in tables}
    before=snapshot()
    response=client.post('/mercado-livre/simulate',base_url='https://localhost',data={'csrf_token':token})
    assert response.status_code==200 and '3 produtos fictícios'.encode() in response.data
    assert b'89,90' in response.data and before==snapshot()
    assert not key.exists()
    assert client.post('/ml/connect',base_url='https://localhost').status_code==403

def test_save_invalidates_old_tokens(setup_panel):
    client,db,key=setup_panel;token=csrf(client)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE ml_credentials SET access_token_encrypted='old', refresh_token_encrypted='old',status='autorizado'")
        c.execute("INSERT INTO oauth_pending VALUES ('state','browser','verifier','redirect',9999999999)")
    client.post('/mercado-livre/save',base_url='https://localhost',data={'csrf_token':token,'client_id':'123','client_secret':'synthetic'})
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT access_token_encrypted,refresh_token_encrypted,status FROM ml_credentials').fetchone()==(None,None,'desconectado')
        assert c.execute('SELECT count(*) FROM oauth_pending').fetchone()[0]==0
