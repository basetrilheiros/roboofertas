import re
from urllib.parse import urlparse
from unittest.mock import Mock
import pytest
from web.app import create_app
from services.ml_panel import save_configuration
from database.connection import get_db

ORIGIN='https://127.0.0.1:5000'
@pytest.fixture
def form(tmp_path):
    db=tmp_path/'test.db';key=tmp_path/'key';transport=Mock()
    app=create_app({'TESTING':True,'DB_PATH':db,'KEY_FILE':key,'SECRET_KEY':'test',
                   'ML_REAL_OAUTH_ENABLED':True,'ML_TEST_TRANSPORT':transport})
    with get_db(db) as c:save_configuration(c,'123','fake-secret',ORIGIN+'/ml/callback',key)
    client=app.test_client()
    page=client.get('/mercado-livre',base_url=ORIGIN)
    token=re.search(rb'name="csrf_token" value="([^"]+)"',page.data).group(1).decode()
    return client,token,db,transport

@pytest.mark.parametrize('headers',[{}, {'Origin':'null'}, {'Origin':ORIGIN},
    {'Origin':'null','Sec-Fetch-Site':'same-origin'},
    {'Referer':ORIGIN+'/mercado-livre','Sec-Fetch-Site':'same-origin'}])
def test_valid_session_csrf_with_browser_header_variations(form,headers):
    client,token,db,transport=form
    response=client.post('/ml/connect',base_url=ORIGIN,headers=headers,data={'csrf_token':token})
    assert response.status_code==303 and urlparse(response.location).hostname=='auth.mercadolivre.com.br'
    transport.exchange.assert_not_called()
    with get_db(db) as c:assert c.execute('SELECT count(*) FROM oauth_pending').fetchone()[0]==1

@pytest.mark.parametrize('headers,token_override',[
    ({'Origin':'https://foreign.invalid'},None),
    ({'Origin':'null','Sec-Fetch-Site':'cross-site'},None),
    ({'Referer':'https://foreign.invalid/'},None),
    ({'Origin':ORIGIN},'invalid'),
    ({'Origin':'null'},''),
    ({},'')])
def test_foreign_or_missing_csrf_never_starts_oauth(form,headers,token_override):
    client,token,db,transport=form
    response=client.post('/ml/connect',base_url=ORIGIN,headers=headers,
                         data={'csrf_token':token if token_override is None else token_override})
    assert response.status_code==303 and response.location=='/mercado-livre'
    transport.exchange.assert_not_called()
    with get_db(db) as c:assert c.execute('SELECT count(*) FROM oauth_pending').fetchone()[0]==0
