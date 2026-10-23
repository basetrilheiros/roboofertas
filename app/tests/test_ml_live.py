import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, parse_qs
from unittest.mock import Mock
import pytest
from web.app import create_app
from database.connection import get_db
from services.crypto import encrypt_secret, decrypt_secret
from services.ml_panel import save_configuration
from services.ml_live import search, access_token, validate_redirect_uri, safe_link
from services.oauth_connection import OAuthConnection

ORIGIN='https://127.0.0.1:5000'
PUBLIC='https://conexao.basetrilheiros.com.br/ml/callback'

@pytest.fixture
def live(tmp_path):
    db=tmp_path/'live.db'; key=tmp_path/'live.key'
    factory=Mock(); transport=Mock()
    app=create_app({'TESTING':True,'DB_PATH':db,'KEY_FILE':key,'SECRET_KEY':'testing',
        'ML_REAL_OAUTH_ENABLED':True,'ML_TEST_CLIENT_FACTORY':factory,'ML_TEST_TRANSPORT':transport})
    with get_db(db) as c:
        save_configuration(c,'123','synthetic',PUBLIC,key)
        c.execute("UPDATE ml_credentials SET status='autorizado',access_token_encrypted=?,refresh_token_encrypted=?,token_expires_at=?",
            (encrypt_secret('test-access',key),encrypt_secret('test-refresh',key),
            (datetime.now(timezone.utc)+timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')))
    client=app.test_client()
    page=client.get('/mercado-livre',base_url=ORIGIN)
    csrf=re.search(rb'name="csrf_token" value="([^"]+)"',page.data).group(1).decode()
    return client,csrf,db,key,factory,transport

def test_public_redirect_and_fragment_completion(live):
    client,csrf,db,key,_,transport=live
    transport.exchange.return_value={'access_token':'new-access','refresh_token':'new-refresh','expires_in':3600,'token_type':'bearer'}
    response=client.post('/ml/connect',base_url=ORIGIN,headers={'Origin':ORIGIN},data={'csrf_token':csrf})
    params=parse_qs(urlsplit(response.location).query)
    assert params['redirect_uri']==[PUBLIC]
    result=client.post('/ml/complete',base_url=ORIGIN,headers={'Origin':ORIGIN},
        data={'csrf_token':csrf,'state':params['state'][0],'code':'test-code'})
    assert result.status_code==303 and transport.exchange.call_count==1
    client.post('/ml/complete',base_url=ORIGIN,headers={'Origin':ORIGIN},
        data={'csrf_token':csrf,'state':params['state'][0],'code':'test-code'})
    assert transport.exchange.call_count==1
    assert client.post('/ml/complete',base_url=ORIGIN,data={'code':'untrusted'}).status_code==403

def test_search_results_escaped_and_no_commercial_writes(live):
    client,csrf,db,key,factory,_=live
    api=factory.return_value
    api.get_current_user.return_value={'id':1,'nickname':'conta-teste'}
    api.search_items.return_value={'paging':{'total':1},'itens':[{'title':'<script>alert(1)</script>',
        'price_centavos':9990,'currency_id':'BRL','free_shipping':1,'is_full':0,'permalink':'javascript:alert(1)'}]}
    with get_db(db) as c: before=list(c.iterdump())
    response=client.post('/mercado-livre/search',base_url=ORIGIN,headers={'Origin':ORIGIN},data={'csrf_token':csrf,'query':'barraca'})
    assert response.status_code==200
    assert b'&lt;script&gt;' in response.data and b'<script>alert' not in response.data
    assert b'javascript:' not in response.data and b'99,90' in response.data
    assert b'test-access' not in response.data
    with get_db(db) as c: assert list(c.iterdump())==before
    factory.assert_called_once_with(access_token='test-access')
    api.session.close.assert_called_once()

def test_search_rejects_missing_csrf_foreign_and_disconnected(live):
    client,csrf,db,_,factory,_=live
    assert client.post('/mercado-livre/search',base_url=ORIGIN,data={'query':'barraca'}).status_code==403
    assert client.post('/mercado-livre/search',base_url=ORIGIN,headers={'Origin':'https://evil.invalid'},data={'csrf_token':csrf,'query':'barraca'}).status_code==403
    with get_db(db) as c: c.execute("UPDATE ml_credentials SET status='desconectado'")
    response=client.post('/mercado-livre/search',base_url=ORIGIN,headers={'Origin':ORIGIN},data={'csrf_token':csrf,'query':'barraca'})
    assert response.status_code==400
    factory.assert_not_called()

def test_search_denial_no_fake_results(live):
    client,csrf,_,_,factory,_=live
    factory.return_value.get_current_user.return_value={'id':1,'nickname':'teste'}
    factory.return_value.search_items.side_effect=PermissionError('Busca recusada (HTTP 403).')
    response=client.post('/mercado-livre/search',base_url=ORIGIN,headers={'Origin':ORIGIN},data={'csrf_token':csrf,'query':'barraca'})
    assert response.status_code==400 and b'HTTP 403' in response.data and b'Resultados reais para' not in response.data

@pytest.mark.parametrize('uri',['http://evil.invalid/ml/callback','https://user:password@evil.invalid/ml/callback','https://example.org/ml/callback?x=1','https://example.org/ml/callback#x','https://example.org/other'])
def test_invalid_redirect(uri):
    with pytest.raises(ValueError): validate_redirect_uri(uri)

def test_links():
    assert not safe_link('https://mercadolivre.com.br.evil.invalid/')
    assert safe_link('https://produto.mercadolivre.com.br/MLB-123')

def test_token_rotation(live,monkeypatch):
    _,_,db,key,_,_=live
    with get_db(db) as c: c.execute("UPDATE ml_credentials SET token_expires_at='2020-01-01 00:00:00'")
    refresh=Mock(return_value={'access_token':'rotated','refresh_token':'rotated-refresh','expires_in':3600,'token_type':'bearer'})
    monkeypatch.setattr('services.ml_live.ml_auth.refresh_token',refresh)
    assert access_token(db,key)=='rotated'
    assert access_token(db,key)=='rotated'
    assert refresh.call_count==1
    with get_db(db) as c:
        row=c.execute('SELECT * FROM ml_credentials').fetchone()
        assert decrypt_secret(row['refresh_token_encrypted'],key)=='rotated-refresh'

def test_return_page_is_no_store(live):
    client,*_=live
    page=client.get('/ml/return',base_url=ORIGIN)
    assert page.status_code==200 and page.headers['Cache-Control']=='no-store'
    assert "frame-ancestors 'none'" in page.headers['Content-Security-Policy']

def test_live_business_forms_require_csrf(live):
    client,csrf,_,_,_,_=live
    assert client.post('/parameters/save',base_url=ORIGIN,data={}).status_code==403
    page=client.get('/parameters',base_url=ORIGIN)
    assert csrf.encode() in page.data
    assert client.post('/parameters/save',base_url=ORIGIN,headers={'Origin':ORIGIN},data={'csrf_token':csrf}).status_code==302

def test_refresh_failure_disconnects_and_never_retries(live,monkeypatch):
    _,_,db,key,_,_=live
    with get_db(db) as c: c.execute("UPDATE ml_credentials SET token_expires_at='2020-01-01 00:00:00'")
    refresh=Mock(side_effect=ValueError('sensitive provider response'))
    monkeypatch.setattr('services.ml_live.ml_auth.refresh_token',refresh)
    for _ in range(2):
        with pytest.raises(ValueError) as error: access_token(db,key)
        assert 'sensitive' not in str(error.value)
    assert refresh.call_count==1

@pytest.mark.parametrize('uri',['https://basetrilheiros.com.br/ml/callback/','https://basetrilheiros.com.br/ml/callback.html'])
def test_github_pages_redirect_formats(uri):
    assert validate_redirect_uri(uri)==uri
