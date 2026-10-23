import re
from unittest.mock import Mock
import pytest
from web.app import create_app
from database.connection import get_db
from services.ml_panel import save_configuration
from services.crypto import encrypt_secret
from datetime import datetime, timezone, timedelta

@pytest.fixture
def setup_live(tmp_path):
    db=tmp_path/'test.db';key=tmp_path/'key'
    app=create_app({'TESTING':True,'DB_PATH':db,'KEY_FILE':key,'SECRET_KEY':'fake',
                    'ML_REAL_OAUTH_ENABLED':True,'ML_TEST_TRANSPORT':Mock()})
    with get_db(db) as c:save_configuration(c,'123','fake-secret','https://127.0.0.1:5000/ml/callback',key)
    return app.test_client(),db,key

def test_enabled_button_visible_but_get_never_starts_authorization(setup_live):
    client,db,key=setup_live
    response=client.get('/mercado-livre',base_url='https://localhost')
    html=response.data.decode().split('<body>',1)[1]
    assert 'Conectar minha conta' in html and 'action="/ml/connect"' in html
    with get_db(db) as c:
        assert c.execute('SELECT count(*) FROM oauth_pending').fetchone()[0]==0
        assert c.execute('SELECT access_token_encrypted FROM ml_credentials').fetchone()[0] is None
    assert client.post('/ml/prepare',base_url='https://localhost',headers={'Origin':'https://localhost'}).status_code==403

def test_connected_status_and_disconnect_only_local_tokens(setup_live):
    client,db,key=setup_live
    with get_db(db) as c:
        c.execute("UPDATE ml_credentials SET status='autorizado',access_token_encrypted=?,refresh_token_encrypted=?,token_expires_at=?",
                  (encrypt_secret('fake-access',key),encrypt_secret('fake-refresh',key),
                   (datetime.now(timezone.utc)+timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')))
        secret=c.execute('SELECT client_secret_encrypted FROM ml_credentials').fetchone()[0]
    response=client.get('/mercado-livre',base_url='https://localhost')
    assert b'Conta autorizada' in response.data and b'Desconectar deste computador' in response.data
    assert b'fake-access' not in response.data and b'fake-refresh' not in response.data
    assert client.post('/mercado-livre/disconnect',base_url='https://localhost').status_code==400
    token=re.search(rb'name="csrf_token" value="([^"]+)"',response.data).group(1).decode()
    assert client.post('/mercado-livre/disconnect',base_url='https://localhost',data={'csrf_token':token}).status_code==302
    with get_db(db) as c:
        row=c.execute('SELECT * FROM ml_credentials').fetchone()
        assert row['access_token_encrypted'] is None and row['refresh_token_encrypted'] is None
        assert row['client_secret_encrypted']==secret and row['status']=='desconectado'

def test_expired_not_displayed_as_connected(setup_live):
    client,db,key=setup_live
    with get_db(db) as c:
        c.execute("UPDATE ml_credentials SET status='autorizado',access_token_encrypted='synthetic',refresh_token_encrypted='synthetic',token_expires_at='2020-01-01 00:00:00'")
    html=client.get('/mercado-livre',base_url='https://localhost').data.decode()
    assert 'autorização salva expirou' in html and 'Conectar minha conta' in html
    assert 'Tokens salvos com criptografia neste computador.' not in html
