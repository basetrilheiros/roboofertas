"""Explicit, transactional migration of business data only. Never transfers local secrets."""
import argparse
import os
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from database.connection import get_db, is_postgres
from database.migrations import ensure_database
from services.hosted_backup import TABLES


def migrate(source_path, destination):
    if not is_postgres(destination): raise ValueError('Destino deve ser PostgreSQL.')
    business=tuple(t for t in TABLES if t!='ml_credentials')
    source=sqlite3.connect(Path(source_path).resolve().as_uri()+'?mode=ro',uri=True)
    source.row_factory=sqlite3.Row
    try:
        source.execute('BEGIN')
        if source.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('Banco de origem inválido.')
        existing={r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        snapshot={t:([] if t=='affiliate_links' and t not in existing else source.execute('SELECT * FROM '+t).fetchall()) for t in business}
        ensure_database(destination)
        with get_db(destination) as target:
            target.execute('SELECT pg_advisory_xact_lock(71420903)')
            # Do not merge into a populated cloud installation or overwrite credentials.
            for table in business:
                count=target.execute('SELECT count(*) FROM '+table).fetchone()[0]
                if table!='settings' and count: raise ValueError('Destino já possui dados; migração cancelada.')
            credentials=target.execute('SELECT * FROM ml_credentials WHERE id=1').fetchone()
            if credentials['client_id'] or credentials['client_secret_encrypted']:
                raise ValueError('Destino já possui configuração de conta; migração cancelada.')
            target.execute('DELETE FROM settings')
            counts={}
            for table,rows in snapshot.items():
                for row in rows:
                    columns=list(row.keys())
                    target.execute('INSERT INTO '+table+' ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',tuple(row))
                counts[table]=len(rows)
                actual=target.execute('SELECT count(*) FROM '+table).fetchone()[0]
                if actual!=len(rows): raise ValueError('Contagem divergente; migração desfeita.')
                if table not in ('settings','affiliate_links'):
                    target.execute("SELECT setval(pg_get_serial_sequence(?, 'id'), COALESCE((SELECT MAX(id) FROM "+table+"),1), (SELECT count(*)>0 FROM "+table+"))",(table,))
            expected=source.execute('SELECT COALESCE(SUM(comissao_centavos),0) FROM sales').fetchone()[0]
            actual=target.execute('SELECT COALESCE(SUM(comissao_centavos),0) FROM sales').fetchone()[0]
            if actual!=expected: raise ValueError('Total de comissões divergente; migração desfeita.')
            return counts
    finally:
        source.rollback()
        source.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Migrar dados comerciais para um destino vazio. Faça backup e encerre o app local antes.')
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--confirm',action='store_true',help='Confirma o envio dos dados comerciais ao DATABASE_URL configurado.')
    args=parser.parse_args()
    if not args.confirm: parser.error('É necessário --confirm para transmitir os dados.')
    try:
        counts=migrate(args.source,os.environ.get('DATABASE_URL',''))
        print('Migração concluída e conferida. Credenciais não foram copiadas.')
        print('Tabelas copiadas:',len(counts))
    except Exception:
        print('Migração não concluída. O destino não foi mesclado; preserve a origem e verifique a configuração.')
        sys.exit(1)
