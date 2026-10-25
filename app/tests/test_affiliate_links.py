import pytest
from services.affiliate_links import validate_link, save_link, attach_links
from database.connection import get_db
from database.migrations import ensure_database


@pytest.mark.parametrize('url', ['javascript:alert(1)','https://meli.la.evil.test/abc',
    'https://evil.test/sec/abc','https://www.mercadolivre.com.br/p/MLB123',
    'https://user@meli.la/abc','https://meli.la/abc#x'])
def test_rejects_untrusted_or_ordinary_links(url):
    with pytest.raises(ValueError): validate_link(url)


def test_persists_and_updates_exact_offer_without_touching_sales(tmp_path):
    db = tmp_path/'test.db'
    ensure_database(db)
    with get_db(db) as conn:
        save_link(conn, 'MLB123', 'https://meli.la/synthetic1')
        save_link(conn, 'MLB123', 'https://meli.la/synthetic2')
    ensure_database(db)
    with get_db(db) as conn:
        items = [{'ml_item_id': 'MLB123'}, {'ml_item_id': 'MLB456'}]
        attach_links(conn, items)
        assert items[0]['affiliate_link'] == 'https://meli.la/synthetic2'
        assert items[1]['affiliate_link'] == ''
        assert conn.execute('SELECT count(*) FROM affiliate_links').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM sales').fetchone()[0] == 0
        with pytest.raises(ValueError): save_link(conn, '../bad', 'https://meli.la/synthetic')


def test_save_route_requires_csrf_and_rejects_external_links(tmp_path):
    import re
    from web.app import create_app
    app = create_app({'TESTING': True, 'DB_PATH': tmp_path/'web.db',
        'KEY_FILE': tmp_path/'key', 'SECRET_KEY': 'synthetic', 'ML_REAL_OAUTH_ENABLED': True})
    client = app.test_client()
    origin = 'https://127.0.0.1:5000'
    page = client.get('/mercado-livre', base_url=origin)
    assert '<title>Mercado Livre — Base Trilheiros</title>' in page.get_data(as_text=True)
    token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
    data = {'item_id': 'MLB123', 'affiliate_link': 'https://meli.la/synthetic'}
    assert client.post('/mercado-livre/affiliate-link', base_url=origin, data=data).status_code == 403
    data['csrf_token'] = token
    assert client.post('/mercado-livre/affiliate-link', base_url=origin,
        headers={'Origin': origin}, data=data).json['url'] == data['affiliate_link']
    data['affiliate_link'] = 'https://evil.test/secret'
    assert client.post('/mercado-livre/affiliate-link', base_url=origin,
        headers={'Origin': origin}, data=data).status_code == 400
