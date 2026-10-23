"""Offline setup and demonstration. No HTTP transport or token operations."""
import re
from services.crypto import encrypt_secret, DEFAULT_KEY_FILE
from services.ml_client import MercadoLivreClient

def summary(conn):
    from datetime import datetime, timezone
    row = conn.execute("""SELECT client_id,client_secret_encrypted,status,token_expires_at,
        access_token_encrypted,refresh_token_encrypted FROM ml_credentials WHERE id=1""").fetchone()
    saved = bool(row['status']=='autorizado' and row['access_token_encrypted'] and row['refresh_token_encrypted'])
    try:
        expiry = datetime.strptime(str(row['token_expires_at']), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        connected = saved and expiry > datetime.now(timezone.utc)
    except (TypeError, ValueError):
        connected = False
    return {'redirect_uri': conn.execute('SELECT redirect_uri FROM ml_credentials WHERE id=1').fetchone()[0], 'client_id': row['client_id'] or '', 'has_secret': bool(row['client_secret_encrypted']),
            'connected':connected, 'expired':saved and not connected}


def save_configuration(conn, client_id, secret, redirect_uri, key_file=DEFAULT_KEY_FILE):
    from services.ml_live import validate_redirect_uri
    redirect_uri = validate_redirect_uri(redirect_uri)
    client_id=client_id.strip(); secret=secret.strip()
    if not re.fullmatch(r'[0-9]{1,40}',client_id):
        raise ValueError('Informe um App ID válido, contendo somente números.')
    if len(secret)>4096:
        raise ValueError('O segredo informado é muito longo.')
    previous=conn.execute('SELECT client_id,client_secret_encrypted FROM ml_credentials WHERE id=1').fetchone()
    if not secret and (not previous['client_secret_encrypted'] or client_id!=previous['client_id']):
        raise ValueError('Informe o Client Secret ao configurar um novo App ID.')
    encrypted=encrypt_secret(secret,key_file) if secret else previous['client_secret_encrypted']
    # An app-key change must invalidate credentials and pending requests from the prior app.
    conn.execute('''UPDATE ml_credentials SET client_id=?,client_secret_encrypted=?,redirect_uri=?,
      access_token_encrypted=NULL,refresh_token_encrypted=NULL,token_expires_at=NULL,
      status='desconectado',last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=1''',
      (client_id,encrypted,redirect_uri))
    conn.execute('DELETE FROM oauth_pending')

def demonstration():
    raw=[
      {'id':'DEMO-001','title':'Fogareiro de demonstração','price':89.90,'original_price':119.90,
       'shipping':{'free_shipping':True,'logistic_type':'fulfillment'}},
      {'id':'DEMO-002','title':'Lanterna de demonstração','price':49.90,
       'shipping':{'free_shipping':False}},
      {'id':'DEMO-003','title':'Mochila de demonstração','price':159.90,
       'shipping':{'free_shipping':True}}]
    return [MercadoLivreClient.normalize_item(item) for item in raw]
