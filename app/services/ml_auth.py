"""
Módulo de autenticação OAuth 2.0 para a API do Mercado Livre.
Inclui geração de URL de consentimento com proteção CSRF via 'state',
suporte a PKCE e métodos de troca e renovação segura de tokens.
"""
from base64 import urlsafe_b64encode
import hashlib
import hmac
import secrets
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests

AUTH_URL_BASE = "https://auth.mercadolivre.com.br/authorization"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"


def generate_state_token() -> str:
    """Gera um token criptograficamente seguro para o parâmetro 'state' (prevenção contra CSRF)."""
    return secrets.token_urlsafe(32)


def generate_pkce_pair() -> Tuple[str, str]:
    """
    Gera par PKCE (code_verifier e code_challenge via SHA-256 base64url).
    Recomendado por RFC 7636 para maior segurança do fluxo de autorização.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    state: Optional[str] = None,
    code_challenge: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Constrói a URL oficial de consentimento do Mercado Livre Brasil.
    Retorna a URL formatada e o 'state' para conferência no callback.
    """
    state_token = state or generate_state_token()
    params = {
        "response_type": "code",
        "client_id": client_id.strip(),
        "redirect_uri": redirect_uri.strip(),
        "state": state_token,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"

    full_url = f"{AUTH_URL_BASE}?{urlencode(params)}"
    return full_url, state_token


def validate_state(expected_state: Optional[str], received_state: Optional[str]) -> bool:
    """Valida o parâmetro 'state' retornado no callback em tempo constante."""
    if not expected_state or not received_state:
        return False
    return hmac.compare_digest(expected_state, received_state)


def exchange_code_for_token(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: Optional[str] = None,
    timeout: int = 15,
) -> Dict[str, Any]:
    """
    Troca o 'code' temporário por 'access_token' e 'refresh_token'.
    Executa POST oficial para https://api.mercadolibre.com/oauth/token.
    """
    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id.strip(),
        "client_secret": client_secret.strip(),
        "code": code.strip(),
        "redirect_uri": redirect_uri.strip(),
    }
    if code_verifier:
        payload["code_verifier"] = code_verifier

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    return _post_tokens(payload, headers, timeout)


def _post_tokens(payload, headers, timeout):
    """No retries or redirects: authorization codes and refresh tokens are single-use."""
    try:
        response = requests.post(TOKEN_URL, data=payload, headers=headers,
                                 timeout=timeout, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError("Resposta recusada pelo provedor.")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Resposta inválida.")
        return data
    except Exception:
        raise ValueError("Não foi possível concluir a operação de autorização.") from None


def refresh_token(
    client_id: str,
    client_secret: str,
    refresh_token_str: str,
    timeout: int = 15,
) -> Dict[str, Any]:
    """
    Renova um access_token expirado utilizando o refresh_token.
    Executa POST oficial para https://api.mercadolibre.com/oauth/token.
    """
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id.strip(),
        "client_secret": client_secret.strip(),
        "refresh_token": refresh_token_str.strip(),
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    return _post_tokens(payload, headers, timeout)
