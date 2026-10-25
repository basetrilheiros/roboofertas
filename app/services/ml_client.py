"""
Cliente HTTP especializado para consumo da API oficial do Mercado Livre Brasil.
Respeita limites oficiais de requisições, paginação (máx offset + limit <= 1000),
timeouts e tratamento de rate-limiting (HTTP 429).
"""
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

API_BASE_URL = "https://api.mercadolibre.com"
MAX_SEARCH_OFFSET_LIMIT = 1000  # Hard limit documentado pela API do Mercado Livre


class SearchRestricted(PermissionError):
    """The general listing search specifically returned 403."""


class MercadoLivreClient:
    """Cliente HTTP com controle de requisições e normalização de anúncios."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        base_url: str = API_BASE_URL,
        timeout: int = 10,
        min_delay_seconds: float = 0.20,
    ):
        self.access_token = access_token.strip() if access_token else None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.min_delay_seconds = min_delay_seconds
        self._last_request_time = 0.0
        self.session = requests.Session()

    def _throttle(self) -> None:
        """Aplica intervalo mínimo entre requisições para evitar atingir o rate-limit."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.min_delay_seconds:
            time.sleep(self.min_delay_seconds - elapsed)
        self._last_request_time = time.time()

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 2,
    ) -> requests.Response:
        """Executa a requisição HTTP com verificação de autenticação e retry em caso de 429."""
        if not self.access_token:
            raise PermissionError(
                "Access token do Mercado Livre não configurado. Autenticação OAuth 2.0 obrigatória para consultas."
            )

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "User-Agent": "BaseTrilheiros/1.0",
        }

        url = urljoin(f"{self.base_url}/", path.lstrip("/"))

        attempt = 0
        while True:
            self._throttle()
            attempt += 1
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=False,
                )
                if response.status_code == 429 and attempt <= max_retries:
                    # Rate-limited: aguardar backoff exponencial
                    time.sleep(1.5 * attempt)
                    continue
                return response
            except requests.exceptions.SSLError:
                raise ConnectionError("Falha ao validar o certificado HTTPS da API. Confira os certificados da rede; a validação TLS permanece ativa.") from None
            except (requests.ConnectionError, requests.Timeout):
                if attempt <= max_retries:
                    time.sleep(1.0 * attempt)
                    continue
                raise ConnectionError("Não foi possível acessar a API do Mercado Livre. Confira a conexão e tente novamente.") from None

    def get_current_user(self):
        response = self._request("GET", "/users/me", max_retries=0)
        if response.status_code != 200:
            raise ValueError(f"Não foi possível validar a conta (HTTP {response.status_code}). Conecte novamente se a autorização expirou.")
        data = response.json()
        if not isinstance(data, dict) or not data.get("id"):
            raise ValueError("A API não retornou uma identificação válida da conta.")
        return {"id": data["id"], "nickname": str(data.get("nickname", ""))}

    @staticmethod
    def build_search_params(
        query: str,
        category: Optional[str] = None,
        price_min_cents: Optional[int] = None,
        price_max_cents: Optional[int] = None,
        free_shipping: bool = False,
        full_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Valida e constrói o dicionário de parâmetros para o endpoint /sites/MLB/search.
        Garante que offset + limit não ultrapasse o limite rígido de 1.000 itens da API.
        """
        if offset + limit > MAX_SEARCH_OFFSET_LIMIT:
            raise ValueError(
                f"Paginação excede o limite oficial da API: offset ({offset}) + limit ({limit}) > {MAX_SEARCH_OFFSET_LIMIT}."
            )

        params: Dict[str, Any] = {
            "q": query.strip(),
            "limit": min(max(1, limit), 50),
            "offset": max(0, offset),
        }

        if category:
            params["category"] = category.strip()

        # Filtro de faixa de preço oficial (formato: PRICE_MIN-PRICE_MAX)
        if price_min_cents is not None or price_max_cents is not None:
            min_str = f"{price_min_cents / 100:.2f}" if price_min_cents is not None else "*"
            max_str = f"{price_max_cents / 100:.2f}" if price_max_cents is not None else "*"
            params["price"] = f"{min_str}-{max_str}"

        # Filtro de frete grátis
        if free_shipping:
            params["shipping_cost"] = "free"

        # Filtro de Mercado Envios Full
        if full_only:
            params["logistic_type"] = "fulfillment"

        return params

    def search_items(
        self,
        query: str,
        category: Optional[str] = None,
        price_min_cents: Optional[int] = None,
        price_max_cents: Optional[int] = None,
        free_shipping: bool = False,
        full_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Executa consulta no endpoint oficial /sites/MLB/search e normaliza os itens retornados.
        """
        params = self.build_search_params(
            query=query,
            category=category,
            price_min_cents=price_min_cents,
            price_max_cents=price_max_cents,
            free_shipping=free_shipping,
            full_only=full_only,
            limit=limit,
            offset=offset,
        )

        response = self._request("GET", "/sites/MLB/search", params=params)
        
        if response.status_code == 401:
            raise PermissionError("Token de acesso expirado ou inválido (HTTP 401). Renovação necessária.")
        if response.status_code == 403:
            raise SearchRestricted("Acesso negado pela API do Mercado Livre (HTTP 403). A conta pode estar conectada, mas esta busca não foi permitida. Não é possível atribuir a causa apenas às permissões.")
        if response.status_code != 200:
            raise ValueError(f"Consulta recusada pela API (HTTP {response.status_code}). Nenhum resultado foi carregado.")

        data = response.json()
        paging = data.get("paging", {})
        results_raw = data.get("results", [])

        normalized_items = [self.normalize_item(it) for it in results_raw if it.get("id")]

        return {
            "query": query,
            "paging": {
                "total": paging.get("total", 0),
                "offset": paging.get("offset", 0),
                "limit": paging.get("limit", len(results_raw)),
            },
            "total_retornados": len(normalized_items),
            "itens": normalized_items,
        }

    def search_catalog_offers(self, query):
        import re
        response = self._request('GET', '/products/search', params={
            'site_id': 'MLB', 'status': 'active', 'q': query, 'limit': 5})
        if response.status_code != 200:
            raise ValueError(f'Busca geral bloqueada; catálogo também indisponível (HTTP {response.status_code}).')
        data = response.json()
        items, seen, unavailable = [], set(), 0
        products = data.get('results', [])[:5]
        for product in products:
            pid = product.get('id', '')
            if not isinstance(pid, str) or not re.fullmatch(r'MLB[0-9]+', pid):
                continue
            offers = self._request('GET', f'/products/{pid}/items', params={'limit': 4})
            if offers.status_code == 401:
                raise PermissionError('Autorização recusada ao consultar ofertas (HTTP 401). Conecte novamente.')
            if offers.status_code != 200:
                unavailable += 1
                continue
            for offer in offers.json().get('results', [])[:4]:
                iid = offer.get('item_id', '')
                if not isinstance(iid, str) or not re.fullmatch(r'MLB[0-9]+', iid) or iid in seen:
                    continue
                if not isinstance(offer.get('price'), (int, float)) or offer['price'] <= 0:
                    continue
                seen.add(iid)
                raw = dict(offer, id=iid, title=product.get('name') or pid,
                    seller={'id': offer.get('seller_id')},
                    permalink=f'https://www.mercadolivre.com.br/p/{pid}?wid={iid}')
                normalized = self.normalize_item(raw)
                normalized['catalog_product_id'] = pid
                items.append(normalized)
        return {'itens': items, 'paging': {'total': None}, 'source': 'catalog',
            'catalog_products_checked': len(products), 'unavailable_products': unavailable}

    @staticmethod
    def normalize_item(raw: Dict[str, Any]) -> Dict[str, Any]:
        """Extrai e normaliza campos relevantes de um anúncio do Mercado Livre."""
        price_float = float(raw.get("price") or 0.0)
        orig_float = float(raw.get("original_price") or 0.0)
        
        shipping = raw.get("shipping") or {}
        seller = raw.get("seller") or {}
        reputation = seller.get("seller_reputation") or {}

        return {
            "ml_item_id": raw.get("id", "").strip(),
            "title": raw.get("title", "").strip(),
            "price_centavos": int(round(price_float * 100)),
            "original_price_centavos": int(round(orig_float * 100)) if orig_float > 0 else None,
            "currency_id": raw.get("currency_id", "BRL"),
            "permalink": raw.get("permalink", "").strip(),
            "thumbnail_url": raw.get("thumbnail", "").strip(),
            "category_id": raw.get("category_id", "").strip(),
            "is_full": 1 if shipping.get("logistic_type") == "fulfillment" else 0,
            "free_shipping": 1 if shipping.get("free_shipping") is True else 0,
            "seller_id": seller.get("id"),
            "seller_nickname": seller.get("nickname", "").strip(),
            "seller_reputation": reputation.get("power_seller_status") or reputation.get("level_id") or "desconhecido",
            "condition": raw.get("condition", "new"),
        }
