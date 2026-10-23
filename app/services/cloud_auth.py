"""Fail-closed hosted configuration and a single-owner login."""
import hmac
import os
import secrets
import time
from datetime import timedelta
from urllib.parse import urlsplit
from flask import request, session, redirect, url_for, render_template, abort
from werkzeug.security import check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from database.connection import get_db, is_postgres


def configure(app):
    app.config.setdefault('CLOUD_MODE', os.environ.get('BASETRILHEIROS_CLOUD') == '1')
    if not app.config['CLOUD_MODE']: return
    def setting(name): return app.config.get(name) or os.environ.get(name)
    base = (setting('PUBLIC_BASE_URL') or os.environ.get('RENDER_EXTERNAL_URL','')).rstrip('/')
    parsed = urlsplit(base)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.hostname in ('localhost','127.0.0.1')
        or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise RuntimeError('Configure PUBLIC_BASE_URL com a origem HTTPS pública da aplicação.')
    url = setting('DATABASE_URL')
    if not is_postgres(url): raise RuntimeError('O modo online exige DATABASE_URL PostgreSQL.')
    # Require TLS verification for remote database connections. Tests may explicitly use local PostgreSQL.
    from psycopg.conninfo import conninfo_to_dict
    db_settings = conninfo_to_dict(url)
    if not app.testing and (db_settings.get('sslmode') != 'verify-full' or db_settings.get('sslrootcert') != 'system'):
        raise RuntimeError('DATABASE_URL deve usar sslmode=verify-full e sslrootcert=system.')
    password_hash = setting('ADMIN_PASSWORD_HASH') or ''
    secret = setting('BASETRILHEIROS_SECRET_KEY') or ''
    master = os.environ.get('BASETRILHEIROS_MASTER_SECRET','')
    if len(secret)<32 or len(master)<32 or not password_hash.startswith(('scrypt:', 'pbkdf2:sha256:')):
        raise RuntimeError('Configure os segredos persistentes e o hash da senha do administrador.')
    app.config.update(PUBLIC_BASE_URL=base, DATABASE_URL=url, ADMIN_PASSWORD_HASH=password_hash,
        ADMIN_USERNAME=setting('ADMIN_USERNAME') or 'admin', SECRET_KEY=secret,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=8*1024*1024,
        ML_REAL_OAUTH_ENABLED=True, SESSION_COOKIE_NAME='__Host-basetrilheiros')
    # Only the hosting TLS proxy's last protocol header is trusted; Host/IP are not forwarded.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1, x_host=0, x_port=0, x_prefix=0)


def install(app, db):
    if not app.config.get('CLOUD_MODE'): return
    with get_db(db) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS auth_throttle (
            bucket TEXT PRIMARY KEY, failures INTEGER NOT NULL, window_start BIGINT NOT NULL)''')
    def csrf_ok():
        expected=session.get('ml_setup_csrf','')
        actual=request.form.get('csrf_token','') or request.headers.get('X-CSRF-Token','')
        return bool(expected and actual and hmac.compare_digest(expected,actual))
    @app.before_request
    def owner_only():
        if request.path == '/healthz': return None
        origin=app.config['PUBLIC_BASE_URL']
        if not request.is_secure or request.host != urlsplit(origin).netloc: abort(400)
        session.setdefault('ml_setup_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if not csrf_ok(): abort(403)
            source=request.headers.get('Origin')
            if source not in (None,origin): abort(403)
            if request.headers.get('Sec-Fetch-Site') not in (None,'same-origin'): abort(403)
        if request.endpoint not in ('login','static') and not session.get('owner_authenticated'):
            return redirect(url_for('login'),code=303)
        if request.path.startswith('/__local/') or request.path in ('/ml/prepare','/ml/return','/ml/complete'):
            abort(404)
    @app.route('/login',methods=['GET','POST'])
    def login():
        error=None
        if request.method=='POST':
            now=int(time.time())
            with get_db(db) as conn:
                conn.execute('BEGIN IMMEDIATE')
                row=conn.execute("SELECT * FROM auth_throttle WHERE bucket='owner'").fetchone()
                if row and now-row['window_start']<900 and row['failures']>=10:
                    return render_template('login.html',error='Muitas tentativas. Aguarde 15 minutos.'),429
                valid_password=check_password_hash(app.config['ADMIN_PASSWORD_HASH'],request.form.get('password','')[:1024])
                valid_user=hmac.compare_digest(request.form.get('username','').encode(),app.config['ADMIN_USERNAME'].encode())
                if valid_password and valid_user:
                    conn.execute("DELETE FROM auth_throttle WHERE bucket='owner'")
                    session.clear()
                    session['owner_authenticated']=True
                    session['ml_setup_csrf']=secrets.token_urlsafe(32)
                    session.permanent=True
                    return redirect(url_for('dashboard'),code=303)
                if not row or now-row['window_start']>=900:
                    conn.execute("DELETE FROM auth_throttle WHERE bucket='owner'")
                    conn.execute("INSERT INTO auth_throttle VALUES ('owner',1,?)",(now,))
                else:
                    conn.execute("UPDATE auth_throttle SET failures=failures+1 WHERE bucket='owner'")
            error='Usuário ou senha inválidos.'
        return render_template('login.html',error=error),400 if error else 200
    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'),code=303)
    @app.get('/healthz')
    def health(): return {'status':'ok'}
    @app.after_request
    def private_headers(response):
        response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer',
            'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY',
            'Strict-Transport-Security':'max-age=31536000',
            'Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"})
        return response
