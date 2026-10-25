from unittest.mock import Mock
import pytest
from services.ml_client import MercadoLivreClient, SearchRestricted
from services.ml_live import search


def response(status, data):
    return Mock(status_code=status, json=Mock(return_value=data))


def test_catalog_combines_product_and_offers_and_rejects_bad_ids():
    api = MercadoLivreClient('synthetic')
    api._request = Mock(side_effect=[
        response(200, {'results': [{'id': 'MLB123', 'name': 'Barraca'}, {'id': '../users'}]}),
        response(200, {'results': [
            {'item_id': 'MLB456', 'price': 74.99, 'seller_id': 789, 'shipping': {'free_shipping': True}},
            {'item_id': 'MLB456', 'price': 74.99},
            {'item_id': 'MLB999', 'price': None},
            {'item_id': 'evil', 'price': 1}]})])
    result = api.search_catalog_offers('barraca')
    assert len(result['itens']) == 1 and api._request.call_count == 2
    item = result['itens'][0]
    assert item['title'] == 'Barraca' and item['price_centavos'] == 7499
    assert item['seller_id'] == 789 and item['free_shipping'] == 1
    assert item['permalink'] == 'https://www.mercadolivre.com.br/p/MLB123?wid=MLB456'


def test_catalog_marks_partial_failure_without_zero_prices():
    api = MercadoLivreClient('synthetic')
    api._request = Mock(side_effect=[response(200, {'results': [{'id': 'MLB123'}]}), response(403, {})])
    result = api.search_catalog_offers('barraca')
    assert result['itens'] == [] and result['unavailable_products'] == 1


def test_fallback_only_for_general_search_restriction(monkeypatch):
    monkeypatch.setattr('services.ml_live.access_token', lambda *args: 'synthetic')
    api = Mock()
    api.get_current_user.return_value = {'id': 1}
    api.search_items.side_effect = SearchRestricted('403')
    api.search_catalog_offers.return_value = {'itens': [], 'paging': {'total': None}, 'source': 'catalog'}
    assert search(None, None, 'barraca', lambda **kw: api)['source'] == 'catalog'
    api.search_catalog_offers.assert_called_once()
    api.reset_mock()
    api.search_items.side_effect = PermissionError('401')
    with pytest.raises(PermissionError): search(None, None, 'barraca', lambda **kw: api)
    api.search_catalog_offers.assert_not_called()


def test_catalog_expansion_and_end_of_sample():
    api = MercadoLivreClient('synthetic')
    products = [{'id': f'MLB{n}', 'name': 'Lanterna'} for n in range(10)]
    api._request = Mock(side_effect=[response(200, {'results': products})] +
        [response(200, {'results': []}) for _ in products])
    result = api.search_catalog_offers('lanterna', product_limit=10)
    assert result['next_limit'] == 20
    assert api._request.call_args_list[0].kwargs['params']['limit'] == 10
    api._request = Mock(side_effect=[response(200, {'results': products})] +
        [response(200, {'results': []}) for _ in products])
    assert api.search_catalog_offers('lanterna', product_limit=20)['next_limit'] is None
    with pytest.raises(ValueError): api.search_catalog_offers('lanterna', product_limit=500)
