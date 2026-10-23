from pathlib import Path
from unittest.mock import Mock
from urllib.parse import urlparse, parse_qs
import re
import pytest
from database.connection import get_db
from database.migrations import ensure_database
from services.security_migration import migrate_security
from services.ml_panel import save_configuration
from services.oauth_connection import OAuthConnection, OAuthBlocked, rehearse, validate_tokens
from services.crypto import decrypt_secret
from web.app import create_app

URI='https://127.0.0.1:5000/ml/callback'
def tokens():
    return {'access_token':'SYNTHETIC-ACCESS','refresh_token':'SYNTHETIC-REFRESH',
            'expires_in':21600,'token_type':'bearer'}

@pytest.fixture
def flow(tmp_path):
    db=tmp_path/'oauth.db';key=tmp_path/'oauth.key'
    ensure_database(db);migrate_security(db,key)
    with get_db(db) as c:save_configuration(c,'123','SYNTHETIC-SECRET',URI,key)
    transport=Mock();transport.exchange.return_value=tokens()
    return OAuthConnection(db,key,True,transport),transport,db,key

def state_for(flow):
    return parse_qs(urlparse(flow.start('browser',URI)).query)['state'][0]

def test_blocked_by_default_before_transport(flow):
    service,transport,db,key=flow
    locked=OAuthConnection(db,key,transport=transport)
    with pytest.raises(OAuthBlocked):locked.start('browser',URI)
    with pytest.raises(OAuthBlocked):locked.complete('state','browser','code')
    transport.exchange.assert_not_called()

def test_success_persists_and_replay_never_exchanges_again(flow):
    service,transport,db,key=flow;state=state_for(service)
    assert service.complete(state,'browser','SYNTHETIC-CODE')=={'status':'autorizado'}
    with get_db(db) as c:
        row=c.execute('SELECT * FROM ml_credentials').fetchone()
        assert row['status']=='autorizado'
        assert decrypt_secret(row['access_token_encrypted'],key)=='SYNTHETIC-ACCESS'
        assert decrypt_secret(row['refresh_token_encrypted'],key)=='SYNTHETIC-REFRESH'
        assert row['token_expires_at']
    with pytest.raises(ValueError):service.complete(state,'browser','SYNTHETIC-CODE')
    assert transport.exchange.call_count==1
    args=transport.exchange.call_args.args
    assert args[3]==URI and len(args[4])>=43

@pytest.mark.parametrize('case',['wrong-browser','expired','denied','missing-code'])
def test_rejected_before_exchange(flow,case):
    service,transport,db,key=flow;state=state_for(service)
    if case=='expired':
        with get_db(db) as c:c.execute('UPDATE oauth_pending SET expires_at=0')
    with pytest.raises(ValueError):
        service.complete(state,'other' if case=='wrong-browser' else 'browser',
                         None if case=='missing-code' else 'code',denied=case=='denied')
    transport.exchange.assert_not_called()
    if case in ('denied','missing-code'):
        with get_db(db) as c:assert c.execute('SELECT count(*) FROM oauth_pending').fetchone()[0]==0

def test_exchange_failure_consumes_state_and_redacts_error(flow):
    service,transport,db,key=flow;state=state_for(service)
    transport.exchange.side_effect=ValueError('SECRET-MUST-NOT-LEAK')
    with pytest.raises(ValueError) as error:service.complete(state,'browser','code')
    assert 'SECRET-MUST-NOT-LEAK' not in str(error.value)
    with pytest.raises(ValueError):service.complete(state,'browser','code')
    assert transport.exchange.call_count==1
    with get_db(db) as c:
        assert c.execute('SELECT access_token_encrypted FROM ml_credentials').fetchone()[0] is None

def test_app_change_during_exchange_does_not_save_tokens(flow):
    service,transport,db,key=flow;state=state_for(service)
    def exchange(*args):
        with get_db(db) as c:save_configuration(c,'456','NEW-SYNTHETIC-SECRET',URI,key)
        return tokens()
    transport.exchange.side_effect=exchange
    with pytest.raises(ValueError,match='configuração mudou'):service.complete(state,'browser','code')
    with get_db(db) as c:
        assert c.execute('SELECT client_id,access_token_encrypted FROM ml_credentials').fetchone()[:]==('456',None)

@pytest.mark.parametrize('invalid',[
    {}, {'expires_in':True}, {'expires_in':-1}, {'token_type':'other'},
    {'access_token':123}, {'refresh_token':''}])
def test_malformed_tokens_rejected(invalid):
    data=tokens();data.update(invalid)
    if invalid=={}:data={}
    with pytest.raises(ValueError):validate_tokens(data)

def test_rehearsal_route_does_not_modify_live_database(flow):
    _,transport,db,key=flow
    app=create_app({'TESTING':True,'DB_PATH':db,'KEY_FILE':key,'SECRET_KEY':'test'})
    client=app.test_client()
    page=client.get('/mercado-livre',base_url='https://localhost')
    token=re.search(rb'name="csrf_token" value="([^"]+)"',page.data).group(1).decode()
    with get_db(db) as c:before=list(c.iterdump())
    response=client.post('/mercado-livre/rehearse',base_url='https://localhost',data={'csrf_token':token})
    assert response.status_code==200 and b'Ensaio conclu' in response.data
    with get_db(db) as c:assert list(c.iterdump())==before
    assert client.post('/ml/connect',base_url='https://localhost').status_code==403
    transport.exchange.assert_not_called()

def test_enabled_routes_only_with_injected_transport(flow):
    _,transport,db,key=flow
    config={'TESTING':True,'DB_PATH':db,'KEY_FILE':key,'SECRET_KEY':'test',
            'ML_REAL_OAUTH_ENABLED':True,'ML_TEST_TRANSPORT':transport}
    client=create_app(config).test_client()
    page=client.get('/mercado-livre',base_url='https://127.0.0.1:5000')
    csrf=re.search(rb'name="csrf_token" value="([^"]+)"',page.data).group(1).decode()
    result=client.post('/ml/connect',base_url='https://127.0.0.1:5000',
        headers={'Origin':'https://127.0.0.1:5000'},data={'csrf_token':csrf})
    assert result.status_code==303
    state=parse_qs(urlparse(result.location).query)['state'][0]
    result=client.get('/ml/callback?state='+state+'&code=synthetic',base_url='https://127.0.0.1:5000')
    assert result.status_code==303 and result.location=='/mercado-livre'
    assert 'synthetic' not in result.location
    assert result.headers['Cache-Control']=='no-store'
    assert transport.exchange.call_count==1

def test_token_http_transport_no_redirect_no_retry_and_safe_errors(monkeypatch):
    from services.ml_auth import exchange_code_for_token
    request=Mock(return_value=Mock(status_code=302))
    monkeypatch.setattr('services.ml_auth.requests.post',request)
    with pytest.raises(ValueError):exchange_code_for_token('123','secret','code',URI,'verifier')
    assert request.call_count==1
    assert request.call_args.kwargs['allow_redirects'] is False
    request.return_value=Mock(status_code=200)
    request.return_value.json.return_value=tokens()
    assert exchange_code_for_token('123','secret','code',URI,'verifier')['access_token']=='SYNTHETIC-ACCESS'

def test_two_callbacks_only_exchange_once(flow):
    from concurrent.futures import ThreadPoolExecutor
    service,transport,db,key=flow;state=state_for(service)
    def callback():
        try:return service.complete(state,'browser','synthetic')['status']
        except ValueError:return 'rejeitado'
    with ThreadPoolExecutor(max_workers=2) as pool:
        result=list(pool.map(lambda _:callback(),range(2)))
    assert sorted(result)==['autorizado','rejeitado']
    assert transport.exchange.call_count==1

def test_callback_after_recreation_preserves_session_and_pending(flow):
    _,transport,db,key=flow
    config={'TESTING':True,'DB_PATH':db,'KEY_FILE':key,'SECRET_KEY':'stable-test',
            'ML_REAL_OAUTH_ENABLED':True,'ML_TEST_TRANSPORT':transport}
    origin='https://127.0.0.1:5000'
    first=create_app(config).test_client()
    page=first.get('/mercado-livre',base_url=origin)
    csrf=re.search(rb'name="csrf_token" value="([^"]+)"',page.data).group(1).decode()
    target=first.post('/ml/connect',base_url=origin,headers={'Origin':origin},data={'csrf_token':csrf}).location
    state=parse_qs(urlparse(target).query)['state'][0]
    restarted=create_app(config).test_client()
    restarted.set_cookie('session',first.get_cookie('session',domain='127.0.0.1').value,domain='127.0.0.1')
    result=restarted.get('/ml/callback?state='+state+'&code=synthetic',base_url=origin)
    assert result.status_code==303 and transport.exchange.call_count==1


def test_rehearsal_form_is_visible_in_body_not_title(flow):
    from html.parser import HTMLParser
    class Page(HTMLParser):
        in_body=False
        in_title=False
        forms=[]
        body_text=[]
        title_text=[]
        def handle_starttag(self,tag,attrs):
            if tag=='body':self.in_body=True
            if tag=='title':self.in_title=True
            if tag=='form' and self.in_body:self.forms.append(dict(attrs).get('action'))
            assert not (self.in_title and tag in ('section','form','button','input'))
        def handle_endtag(self,tag):
            if tag=='body':self.in_body=False
            if tag=='title':self.in_title=False
        def handle_data(self,data):
            if self.in_body:self.body_text.append(data)
            if self.in_title:self.title_text.append(data)
    _,_,db,key=flow
    client=create_app({'TESTING':True,'DB_PATH':db,'KEY_FILE':key,'SECRET_KEY':'test'}).test_client()
    page=Page();page.feed(client.get('/mercado-livre',base_url='https://localhost').data.decode())
    assert '/mercado-livre/rehearse' in page.forms
    assert 'Testar conexão simulada' in ''.join(page.body_text)
    assert ''.join(page.title_text).strip()=='Mercado Livre — Base Trilheiros'
