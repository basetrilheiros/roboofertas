"""User-supplied links generated in the official affiliate portal; no cookie access."""
import re
from urllib.parse import urlsplit, parse_qs

PROFILE = 'BaseTrilheiros'
TAG = 'whatsapp'
SCHEMA = '''CREATE TABLE IF NOT EXISTS affiliate_links (
 item_id TEXT NOT NULL, profile TEXT NOT NULL, tag TEXT NOT NULL,
 url TEXT NOT NULL, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (item_id, profile, tag))'''


def validate_link(url):
    url = url.strip()
    try:
        p = urlsplit(url)
        if len(url) > 4096 or p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
            raise ValueError()
        short = p.hostname == 'meli.la' and re.fullmatch(r'/[A-Za-z0-9]+', p.path) and not p.query
        official = p.hostname in ('www.mercadolivre.com.br', 'mercadolivre.com.br') and (
            p.path.startswith('/sec/') or
            (p.path.startswith('/social/') and parse_qs(p.query).get('matt_word') == [TAG]
             and parse_qs(p.query).get('matt_tool')))
        if not (short or official) or p.fragment or any(c.isspace() for c in url):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Cole o link de associado gerado no portal oficial, usando BaseTrilheiros / whatsapp.') from None
    return url


def save_link(conn, item_id, url):
    if not re.fullmatch(r'MLB[0-9]+', item_id or ''):
        raise ValueError('Identificação de oferta inválida.')
    url = validate_link(url)
    conn.execute('''INSERT INTO affiliate_links(item_id, profile, tag, url) VALUES (?,?,?,?)
        ON CONFLICT(item_id, profile, tag) DO UPDATE SET url=excluded.url,updated_at=CURRENT_TIMESTAMP''',
        (item_id, PROFILE, TAG, url))
    return url


def attach_links(conn, items):
    links = {r['item_id']: r['url'] for r in conn.execute(
        'SELECT item_id,url FROM affiliate_links WHERE profile=? AND tag=?', (PROFILE, TAG)).fetchall()}
    for item in items:
        item['affiliate_link'] = links.get(item.get('ml_item_id'), '')
