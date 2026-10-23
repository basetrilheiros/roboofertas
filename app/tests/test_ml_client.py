"""
Testes unitários e controlados da prova de viabilidade da integração com Mercado Livre.
Valida formatação de parâmetros, limites de paginação, autenticação OAuth e CSRF state.
"""
import pytest

from services.ml_auth import (
    build_authorization_url,
    generate_pkce_pair,
    generate_state_token,
    validate_state,
)
from services.ml_client import MAX_SEARCH_OFFSET_LIMIT, MercadoLivreClient


def test_build_search_params_validation():
    """Valida a montagem de parâmetros conforme documentação oficial da API."""
    params = MercadoLivreClient.build_search_params(
        query="barraca camping",
        price_min_cents=5000,
        price_max_cents=50000,
        free_shipping=True,
        full_only=True,
        limit=50,
        offset=0,
    )
    assert params["q"] == "barraca camping"
    assert params["price"] == "50.00-500.00"
    assert params["shipping_cost"] == "free"
    assert params["logistic_type"] == "fulfillment"
    assert params["limit"] == 50
    assert params["offset"] == 0


def test_search_params_enforces_hard_limit_1000():
    """Garante que a biblioteca bloqueia requisições com offset + limit > 1000."""
    # Válido: offset 950 + limit 50 = 1000
    p_ok = MercadoLivreClient.build_search_params("fogareiro", limit=50, offset=950)
    assert p_ok["offset"] == 950

    # Inválido: offset 960 + limit 50 = 1010
    with pytest.raises(ValueError, match="Paginação excede o limite oficial da API"):
        MercadoLivreClient.build_search_params("fogareiro", limit=50, offset=960)


def test_client_requires_token_for_search():
    """Garante que sem token configurado nenhuma chamada externa é disparada."""
    client = MercadoLivreClient(access_token=None)
    with pytest.raises(PermissionError, match="Access token do Mercado Livre não configurado"):
        client.search_items("barraca")


def test_normalize_item_fields():
    """Testa a extração padronizada de dados a partir da resposta bruta do Mercado Livre."""
    raw_api_item = {
        "id": "MLB99887766",
        "title": "Bota Impermeável Trilha Trekking Masculina",
        "price": 289.90,
        "original_price": 349.90,
        "currency_id": "BRL",
        "permalink": "https://produto.mercadolivre.com.br/MLB-99887766-bota",
        "thumbnail": "http://http2.mlstatic.com/D_123-I.jpg",
        "category_id": "MLB1234",
        "shipping": {
            "free_shipping": True,
            "logistic_type": "fulfillment",
        },
        "seller": {
            "id": 554433,
            "nickname": "ADVENTURE_STORE",
            "seller_reputation": {
                "power_seller_status": "platinum",
                "level_id": "5_green",
            },
        },
        "condition": "new",
    }

    norm = MercadoLivreClient.normalize_item(raw_api_item)
    assert norm["ml_item_id"] == "MLB99887766"
    assert norm["title"] == "Bota Impermeável Trilha Trekking Masculina"
    assert norm["price_centavos"] == 28990  # R$ 289,90
    assert norm["original_price_centavos"] == 34990  # R$ 349,90
    assert norm["is_full"] == 1
    assert norm["free_shipping"] == 1
    assert norm["seller_nickname"] == "ADVENTURE_STORE"
    assert norm["seller_reputation"] == "platinum"


def test_oauth_state_generation_and_validation():
    """Valida proteção CSRF no fluxo de autorização OAuth."""
    state1 = generate_state_token()
    state2 = generate_state_token()
    assert state1 != state2
    assert len(state1) >= 32

    # Validação idêntica
    assert validate_state(state1, state1) is True
    # Validação com state diferente deve falhar
    assert validate_state(state1, state2) is False
    assert validate_state(state1, None) is False


def test_oauth_url_and_pkce():
    """Valida construção correta da URL oficial de login do Mercado Livre com PKCE."""
    verifier, challenge = generate_pkce_pair()
    assert len(verifier) >= 43
    assert len(challenge) >= 43

    url, state = build_authorization_url(
        client_id="123456789",
        redirect_uri="http://127.0.0.1:5000/ml/callback",
        code_challenge=challenge,
    )

    assert "https://auth.mercadolivre.com.br/authorization?" in url
    assert "client_id=123456789" in url
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A5000%2Fml%2Fcallback" in url
    assert f"state={state}" in url
    assert f"code_challenge={challenge}" in url
    assert "code_challenge_method=S256" in url
