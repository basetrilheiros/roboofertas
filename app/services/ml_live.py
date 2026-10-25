"""Manual authenticated reads. No background jobs or commercial-data writes."""
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from database.connection import get_db
from services.crypto import decrypt_secret, encrypt_secret
from services.oauth_connection import validate_tokens
from services import ml_auth
from services.ml_client import MercadoLivreClient, SearchRestricted


def validate_redirect_uri(value):
    value = value.strip()
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == 'https' and parsed.hostname and not parsed.username
                 and not parsed.password and not parsed.query and not parsed.fragment
                 and parsed.path in ('/ml/callback', '/ml/callback/', '/ml/callback.html') and parsed.port in (None, 443))
        if parsed.hostname == '127.0.0.1':
            valid = parsed.scheme == 'https' and parsed.path == '/ml/callback' and not parsed.query and not parsed.fragment and not parsed.username and not parsed.password and parsed.port == 5000
        if not valid or len(value) > 2048:
            raise ValueError()
    except ValueError:
        raise ValueError('Use um endereço HTTPS de retorno em /ml/callback, /ml/callback/ ou /ml/callback.html, sem parâmetros.') from None
    return value


def access_token(db_path, key_file):
    # Serialize refresh-token rotation across threads/processes. Never retry a refresh.
    with get_db(db_path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM ml_credentials WHERE id=1').fetchone()
        if not row or row['status'] != 'autorizado' or not row['access_token_encrypted']:
            raise ValueError('Conecte sua conta antes de consultar o Mercado Livre.')
        try:
            expiry = datetime.strptime(str(row['token_expires_at']), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        except ValueError:
            raise ValueError('A autorização salva é inválida. Conecte novamente.') from None
        if expiry > datetime.now(timezone.utc):
            return decrypt_secret(row['access_token_encrypted'], key_file)
        try:
            data = validate_tokens(ml_auth.refresh_token(row['client_id'],
                decrypt_secret(row['client_secret_encrypted'], key_file),
                decrypt_secret(row['refresh_token_encrypted'], key_file)))
        except Exception:
            conn.execute("UPDATE ml_credentials SET access_token_encrypted=NULL,refresh_token_encrypted=NULL,token_expires_at=NULL,status='desconectado' WHERE id=1")
            conn.commit()  # A failed single-use refresh is never retried automatically.
            raise ValueError('Não foi possível renovar a autorização. Conecte novamente antes de tentar outra consulta.') from None
        expiry = datetime.now(timezone.utc) + timedelta(seconds=data['expires_in'] - 60)
        conn.execute('''UPDATE ml_credentials SET access_token_encrypted=?,refresh_token_encrypted=?,
            token_expires_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=1''',
            (encrypt_secret(data['access_token'], key_file), encrypt_secret(data['refresh_token'], key_file),
             expiry.strftime('%Y-%m-%d %H:%M:%S')))
        return data['access_token']


def safe_link(value):
    try:
        p = urlsplit(value)
        return value if (p.scheme == 'https' and p.hostname and not p.username and not p.password
            and (p.hostname == 'mercadolivre.com.br' or p.hostname.endswith('.mercadolivre.com.br'))) else ''
    except (ValueError, TypeError):
        return ''


def search(db_path, key_file, query, client_factory=MercadoLivreClient):
    query = query.strip()
    if not 2 <= len(query) <= 120:
        raise ValueError('Informe uma busca com 2 a 120 caracteres.')
    client = client_factory(access_token=access_token(db_path, key_file))
    try:
        # Probe account separately so a search restriction is not mistaken for failed OAuth.
        account = client.get_current_user()
        try:
            result = client.search_items(query, limit=20)
        except SearchRestricted:
            result = client.search_catalog_offers(query)
        for item in result['itens']:
            item['permalink'] = safe_link(item.get('permalink'))
        return {'query': query, 'account': account, 'items': result['itens'],
                'total': result['paging']['total'], 'source': result.get('source', 'listings'),
                'unavailable_products': result.get('unavailable_products', 0),
                'checked_at': datetime.now(timezone.utc).isoformat()}
    finally:
        client.session.close()
