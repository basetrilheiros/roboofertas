"""Consistent logical backup streamed to the owner, never stored on ephemeral disk."""
import json
from database.connection import get_db

TABLES=('settings','monitored_products','imports','sales','sale_status_history','audit_events','scheduler_logs',
 'discovery_runs','discovered_products','price_history','curated_offers','user_decisions_feedback','ml_credentials','affiliate_links')

def export_snapshot(url):
    with get_db(url) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        data={table:[dict(row) for row in conn.execute('SELECT * FROM '+table).fetchall()] for table in TABLES}
    return json.dumps({'format':'basetrilheiros-logical-v1','tables':data,
        'note':'Credenciais permanecem cifradas; guarde separadamente a chave mestre original.'},
        ensure_ascii=False,default=str).encode('utf-8')
