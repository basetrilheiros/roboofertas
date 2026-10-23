"""OAuth orchestration. Disabled by default; all transports require explicit enablement."""
from datetime import datetime, timezone
import hashlib
import json
import tempfile
from pathlib import Path

from database.connection import get_db
from services.crypto import decrypt_secret, encrypt_secret
from services.oauth_pending import begin, consume
from services import ml_auth

class OAuthBlocked(ValueError):
    pass

class TokenTransport:
    def exchange(self, client_id, secret, code, uri, verifier):
        return ml_auth.exchange_code_for_token(client_id, secret, code, uri, verifier)


def validate_tokens(data):
    if not isinstance(data, dict):
        raise ValueError('Resposta de autorização inválida.')
    for field in ('access_token', 'refresh_token'):
        if not isinstance(data.get(field), str) or not data[field].strip() or len(data[field]) > 8192:
            raise ValueError('Resposta de autorização incompleta.')
    expiry=data.get('expires_in')
    if type(expiry) is not int or not 60 < expiry <= 31536000:
        raise ValueError('Prazo de autorização inválido.')
    if str(data.get('token_type', '')).lower() != 'bearer':
        raise ValueError('Tipo de autorização inválido.')
    return data


def fingerprint(row):
    return hashlib.sha256(json.dumps([row['client_id'], row['client_secret_encrypted'], row['redirect_uri']],
                                    separators=(',', ':')).encode()).hexdigest()

class OAuthConnection:
    def __init__(self, db_path, key_file, enabled=False, transport=None):
        from database.connection import is_postgres
        self.db_path=db_path if is_postgres(db_path) else Path(db_path)
        self.key_file=Path(key_file)
        self.enabled=enabled
        self.transport=transport if transport is not None else TokenTransport()

    def guard(self):
        if self.enabled is not True:
            raise OAuthBlocked('Conexão real desativada. Esta etapa permite somente testes simulados.')

    def start(self, browser, redirect_uri):
        self.guard()
        with get_db(self.db_path) as conn:
            row=conn.execute('SELECT * FROM ml_credentials WHERE id=1').fetchone()
            if not row or not row['client_id'] or not row['client_secret_encrypted']:
                raise ValueError('Salve o App ID e o Client Secret antes de conectar.')
            if row['redirect_uri'] != redirect_uri:
                raise ValueError('O endereço de retorno precisa corresponder à configuração salva.')
            # Fail before redirect when an existing key/secret cannot be read.
            decrypt_secret(row['client_secret_encrypted'], self.key_file)
            return begin(conn, row['client_id'], redirect_uri, browser+fingerprint(row), self.key_file)

    def complete(self, state, browser, code=None, denied=False):
        self.guard()
        if not browser or not state or len(state)>256:
            raise ValueError('Autorização inválida ou expirada.')
        # The single-use state is committed BEFORE the external exchange. A failure never restores it.
        with get_db(self.db_path) as conn:
            row=conn.execute('SELECT * FROM ml_credentials WHERE id=1').fetchone()
            original=fingerprint(row)
            verifier, uri=consume(conn,state,browser+original,self.key_file)
            client_id=row['client_id']
            secret=decrypt_secret(row['client_secret_encrypted'],self.key_file)
        if denied:
            raise ValueError('Autorização cancelada. Nenhum token foi solicitado.')
        if not isinstance(code,str) or not code.strip() or len(code)>4096:
            raise ValueError('Código de autorização ausente ou inválido. Inicie novamente.')
        try:
            data=validate_tokens(self.transport.exchange(client_id,secret,code,uri,verifier))
        except Exception:
            # Provider errors can echo secrets/codes; never copy their text into UI, storage or logs.
            raise ValueError('Não foi possível concluir a autorização. Inicie uma nova tentativa.') from None
        access=encrypt_secret(data['access_token'], self.key_file)
        refresh=encrypt_secret(data['refresh_token'], self.key_file)
        expiry=datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()+data['expires_in']-60,
                                      timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        with get_db(self.db_path) as conn:
            conn.execute('BEGIN IMMEDIATE')
            current=conn.execute('SELECT * FROM ml_credentials WHERE id=1').fetchone()
            if fingerprint(current)!=original:
                raise ValueError('A configuração mudou durante a autorização. Inicie novamente.')
            conn.execute('''UPDATE ml_credentials SET access_token_encrypted=?,refresh_token_encrypted=?,
                token_expires_at=?,status='autorizado',last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=1''',
                (access,refresh,expiry))
        return {'status':'autorizado'}


def rehearse():
    """Exercise real orchestration using a disposable database, synthetic keys and an in-memory transport."""
    from urllib.parse import urlparse, parse_qs
    from database.migrations import ensure_database
    from services.security_migration import migrate_security
    from services.ml_panel import save_configuration
    class SimulatedTransport:
        calls=0
        def exchange(self, client_id, secret, code, uri, verifier):
            self.calls+=1
            if client_id!='123456' or secret!='segredo-ficticio' or code!='codigo-ficticio' or len(verifier)<43:
                raise ValueError('Entrada simulada inválida')
            return {'access_token':'acesso-ficticio','refresh_token':'renovacao-ficticia',
                    'expires_in':21600,'token_type':'bearer'}
    with tempfile.TemporaryDirectory(prefix='base-oauth-simulado-') as directory:
        db=Path(directory)/'test.db'; key=Path(directory)/'test.key'
        ensure_database(db);migrate_security(db,key)
        uri='https://127.0.0.1:5000/ml/callback'
        with get_db(db) as conn:save_configuration(conn,'123456','segredo-ficticio',uri,key)
        transport=SimulatedTransport()
        flow=OAuthConnection(db,key,enabled=True,transport=transport)
        url=flow.start('navegador-ficticio',uri)
        state=parse_qs(urlparse(url).query)['state'][0]
        flow.complete(state,'navegador-ficticio','codigo-ficticio')
        with get_db(db) as conn:
            row=conn.execute('SELECT * FROM ml_credentials WHERE id=1').fetchone()
            if decrypt_secret(row['access_token_encrypted'],key)!='acesso-ficticio':
                raise ValueError('Falha na conferência local')
            if row['status']!='autorizado' or not row['refresh_token_encrypted'].startswith('fernet:v1:'):
                raise ValueError('Falha na persistência simulada')
        try:flow.complete(state,'navegador-ficticio','codigo-ficticio')
        except ValueError:pass
        else:raise ValueError('Reutilização não foi bloqueada')
        if transport.calls!=1:raise ValueError('Troca duplicada')
    return ['State e PKCE gerados e validados.',
            'Retorno de autorização processado com resposta fictícia.',
            'Tokens fictícios criptografados em uma base temporária.',
            'Reutilização da autorização rejeitada.',
            'Base temporária e chave de teste removidas ao concluir.']
