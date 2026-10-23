"""
Servidor Web Flask da Base Trilheiros (Fase 1).
Vinculado estritamente a 127.0.0.1 com templates Jinja2 e rotas de curadoria.
"""
from datetime import datetime
import io
import json
from pathlib import Path
import sqlite3
from typing import Optional

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    make_response,
    url_for,
)

from config import (
    APP_NAME,
    APP_VERSION,
    DB_PATH,
    HOST,
    PORT,
    REPORTS_DIR,
    SECRET_KEY,
)
from database.connection import get_db
from database.migrations import ensure_database
from models.audit import list_audit_events, list_imports
from models.monitored import (
    count_monitored,
    create_monitored,
    delete_monitored,
    list_monitored,
    toggle_monitored_status,
)
from models.sales import (
    get_sales_summary,
    list_categories,
    list_sales,
    update_sale_status,
)
from models.settings import get_settings, update_settings
from services.backup import create_backup, list_backups
from services.importer import (
    execute_import,
    generate_content_hash,
    preview_import,
)
from services.parser import normalize_text, parse_pasted_text, parse_xlsx


def create_app(test_config: Optional[dict] = None) -> Flask:
    """Cria e configura a instância do aplicativo Flask."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    import platform
    @app.context_processor
    def runtime_platform():
        return {"platform_label": platform.system()}

    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["ML_REAL_OAUTH_ENABLED"] = False
    if test_config:
        app.config.update(test_config)

    from services.cloud_auth import configure, install
    configure(app)
    cloud = app.config.get("CLOUD_MODE", False)
    # An explicit SQLite path remains supported for isolated local tests.
    db_file = app.config["DATABASE_URL"] if cloud else Path(app.config.get("DB_PATH", DB_PATH))
    ensure_database(db_file)
    from services.security_migration import migrate_security
    from services.crypto import DEFAULT_KEY_FILE
    key_file = Path(app.config.get("KEY_FILE", DEFAULT_KEY_FILE))
    migrate_security(db_file, key_file)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=True)
    if not app.config.get("TESTING") and not cloud:
        import hashlib
        from services.crypto import get_or_create_master_key
        app.secret_key = hashlib.sha256(get_or_create_master_key(key_file) + b"session-2.1-A").digest()

    install(app, db_file)

    @app.post("/ml/prepare")
    def ml_prepare():
        import secrets
        from services.oauth_pending import begin
        if app.config.get("ML_REAL_OAUTH_ENABLED") is True:
            return jsonify(error="Use o botão Conectar minha conta no painel."), 403
        # Browser POST must come from this HTTPS origin.
        if not request.is_secure or request.headers.get("Origin") != request.host_url.rstrip("/"):
            return jsonify(error="Origem HTTPS local obrigatória"), 403
        browser = session.get("oauth_browser") or secrets.token_urlsafe(32)
        session["oauth_browser"] = browser
        with get_db(db_file) as conn:
            row = conn.execute("SELECT client_id FROM ml_credentials WHERE id=1").fetchone()
            if not row or not row[0]:
                return jsonify(error="Client ID não configurado"), 400
            uri = f"https://127.0.0.1:{PORT}/ml/callback"
            authorization_url = begin(conn, row[0], uri, browser, key_file)
        return jsonify(authorization_url=authorization_url, expires_in=600,
                       status="Preparado localmente. OAuth real desabilitado neste incremento.")

    @app.post("/ml/connect")
    def ml_connect():
        if app.config.get("ML_REAL_OAUTH_ENABLED") is not True:
            return jsonify(error="Conexão real desativada. Use o teste simulado."), 403
        if not ml_connection_form_valid():
            flash("Não foi possível validar esta tentativa. Reabra a página Mercado Livre e clique novamente em Conectar minha conta.", "error")
            return redirect(url_for("ml_configuration"), code=303)
        from services.oauth_connection import OAuthConnection
        transport = app.config.get("ML_TEST_TRANSPORT") if app.testing else None
        browser = session.get("oauth_browser") or secrets.token_urlsafe(32)
        session["oauth_browser"] = browser
        try:
            target = OAuthConnection(db_file, key_file, True, transport).start(
                browser, saved_redirect_uri())
        except ValueError:
            flash("Confira as credenciais e o endereço de retorno antes de conectar.", "error")
            return redirect(url_for("ml_configuration"))
        return redirect(target, code=303)

    @app.get("/ml/callback")
    def ml_callback():
        if app.config.get("ML_REAL_OAUTH_ENABLED") is True:
            from services.oauth_connection import OAuthConnection
            transport = app.config.get("ML_TEST_TRANSPORT") if app.testing else None
            try:
                OAuthConnection(db_file, key_file, True, transport).complete(
                    request.args.get("state"), session.get("oauth_browser"),
                    request.args.get("code"), denied=bool(request.args.get("error")))
                flash("Autorização concluída. Nenhuma pesquisa de produtos foi executada.", "success")
            except ValueError as error:
                flash(str(error), "error")
            # Strip callback code/state from the browser address immediately.
            return redirect(url_for("ml_configuration"), code=303)
        from services.oauth_pending import consume
        try:
            with get_db(db_file) as conn:
                consume(conn, request.args.get("state"), session.get("oauth_browser"), key_file)
        except ValueError:
            return jsonify(error="Autorização inválida ou expirada"), 400
        return jsonify(status="Callback validado localmente; troca de tokens desabilitada"), 200

    @app.after_request
    def protect_oauth_response(response):
        if request.path.startswith(("/ml/", "/mercado-livre")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response


    def _conn():
        return get_db(db_file)

    # Setup screen: only local storage and deterministic offline demonstration.
    import secrets
    import hmac
    from services.ml_panel import summary, save_configuration, demonstration

    def ml_csrf_valid():
        expected = session.get("ml_setup_csrf")
        received = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
        return bool(expected and received and hmac.compare_digest(expected.encode(), received.encode()))

    def ml_connection_form_valid():
        # A synchronizer CSRF token remains mandatory even for browsers that omit Origin
        # or send an opaque 'null' origin with a local, self-signed HTTPS certificate.
        expected = app.config["PUBLIC_BASE_URL"] if cloud else f"https://127.0.0.1:{PORT}"
        from urllib.parse import urlsplit
        if not request.is_secure or request.host != urlsplit(expected).netloc or not ml_csrf_valid():
            return False
        origin = request.headers.get("Origin")
        if origin not in (None, "null", expected):
            return False
        fetch_site = request.headers.get("Sec-Fetch-Site")
        if fetch_site is not None and fetch_site != "same-origin":
            return False
        referer = request.headers.get("Referer")
        if referer:
            from urllib.parse import urlsplit
            try:
                parsed = urlsplit(referer)
                if f"{parsed.scheme}://{parsed.netloc}" != expected:
                    return False
            except ValueError:
                return False
        return True

    @app.before_request
    def protect_live_mode_forms():
        if app.config.get("ML_REAL_OAUTH_ENABLED") is not True and not cloud:
            return None
        session.setdefault("ml_setup_csrf", secrets.token_urlsafe(32))
        if request.method == "POST" and not request.path.startswith(("/__local/", "/ml/", "/mercado-livre/")):
            if not ml_connection_form_valid():
                return "Sessão expirada ou origem inválida. Reabra o painel.", 403

    @app.context_processor
    def global_form_token():
        return {"global_csrf": session.get("ml_setup_csrf", ""), "cloud_mode": cloud}

    def saved_redirect_uri():
        if cloud: return app.config["PUBLIC_BASE_URL"] + "/ml/callback"
        with _conn() as conn:
            row = conn.execute("SELECT redirect_uri FROM ml_credentials WHERE id=1").fetchone()
        value = row[0] if row else ""
        return value if value.startswith("https://") else f"https://127.0.0.1:{PORT}/ml/callback"

    def ml_setup_render(products=None, status=200, rehearsal=None, live_result=None):
        session.setdefault("ml_setup_csrf", secrets.token_urlsafe(32))
        with _conn() as conn:
            credentials = summary(conn)
        return render_template("mercado_livre.html", credentials=credentials,
            csrf_token=session["ml_setup_csrf"], products=products, rehearsal=rehearsal, live_result=live_result,
            real_enabled=app.config.get("ML_REAL_OAUTH_ENABLED") is True,
            redirect_uri=saved_redirect_uri()), status

    @app.get("/mercado-livre")
    def ml_configuration():
        return ml_setup_render()

    @app.post("/mercado-livre/save")
    def ml_configuration_save():
        if not ml_csrf_valid():
            return "Sessão expirada. Reabra a página Mercado Livre e tente novamente.", 400
        try:
            with _conn() as conn:
                save_configuration(conn, request.form.get("client_id", ""),
                    request.form.get("client_secret", ""),
                    (saved_redirect_uri() if cloud else request.form.get("redirect_uri", f"https://127.0.0.1:{PORT}/ml/callback")), key_file)
        except ValueError as error:
            flash(str(error), "error")
            return ml_setup_render(status=400)
        except Exception:
            flash("Não foi possível salvar. A configuração anterior foi preservada.", "error")
            return ml_setup_render(status=500)
        flash("Configuração salva com proteção local. A conta permanece desconectada até você autorizar.", "success")
        return redirect(url_for("ml_configuration"))

    @app.get("/ml/return")
    def ml_return():
        # A public static bridge returns code/state in the fragment (never sent in HTTP).
        session.setdefault("ml_setup_csrf", secrets.token_urlsafe(32))
        response = make_response(render_template("ml_return.html", csrf_token=session["ml_setup_csrf"]))
        response.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.post("/ml/complete")
    def ml_complete():
        if app.config.get("ML_REAL_OAUTH_ENABLED") is not True or not ml_connection_form_valid():
            return "Tentativa inválida. Reabra a página Mercado Livre.", 403
        from services.oauth_connection import OAuthConnection
        transport = app.config.get("ML_TEST_TRANSPORT") if app.testing else None
        try:
            OAuthConnection(db_file, key_file, True, transport).complete(
                request.form.get("state"), session.get("oauth_browser"),
                request.form.get("code"), denied=bool(request.form.get("error")))
            flash("Conta autorizada. Agora você pode executar uma busca manual.", "success")
        except ValueError as error:
            flash(str(error), "error")
        return redirect(url_for("ml_configuration"), code=303)

    @app.post("/mercado-livre/search")
    def ml_search():
        if app.config.get("ML_REAL_OAUTH_ENABLED") is not True:
            return "Consultas reais desativadas nesta execução.", 403
        if not ml_connection_form_valid():
            return "Sessão expirada ou origem inválida. Reabra a página Mercado Livre.", 403
        from services.ml_live import search
        try:
            factory = app.config.get("ML_TEST_CLIENT_FACTORY") if app.testing else None
            kwargs = {"client_factory": factory} if factory else {}
            result = search(db_file, key_file, request.form.get("query", ""), **kwargs)
            return ml_setup_render(live_result=result)
        except (ValueError, PermissionError, ConnectionError) as error:
            flash(str(error), "error")
            return ml_setup_render(status=400)
        except Exception:
            flash("A consulta não concluiu. Nenhum resultado foi carregado e nenhum dado comercial foi alterado.", "error")
            return ml_setup_render(status=502)

    @app.post("/mercado-livre/simulate")
    def ml_simulation():
        if not ml_csrf_valid():
            return "Sessão expirada. Reabra a página Mercado Livre e tente novamente.", 400
        return ml_setup_render(products=demonstration())

    @app.post("/mercado-livre/disconnect")
    def ml_disconnect():
        if not ml_csrf_valid():
            return "Sessão expirada. Reabra a página Mercado Livre e tente novamente.", 400
        with _conn() as conn:
            conn.execute("""UPDATE ml_credentials SET access_token_encrypted=NULL,
                refresh_token_encrypted=NULL,token_expires_at=NULL,status='desconectado',
                last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=1""")
            conn.execute("DELETE FROM oauth_pending")
        flash("Tokens removidos deste computador. Para revogar a permissão no Mercado Livre, use o portal da plataforma.", "success")
        return redirect(url_for("ml_configuration"))

    @app.post("/mercado-livre/rehearse")
    def ml_rehearsal():
        if not ml_csrf_valid():
            return "Sessão expirada. Reabra a página Mercado Livre e tente novamente.", 400
        from services.oauth_connection import rehearse
        try:
            results = rehearse()
        except Exception:
            flash("O ensaio local não concluiu. Nenhuma autorização real foi executada.", "error")
            return ml_setup_render(status=500)
        return ml_setup_render(rehearsal=results)

    @app.after_request
    def sign_sales_preview(response):
        if cloud and request.endpoint in ("sales_preview_xlsx", "sales_preview_paste", "sales_preview_sample") and response.status_code == 200:
            from itsdangerous import URLSafeTimedSerializer
            data = response.get_json()
            if data and data.get("success"):
                data["source_info"]["signature"] = URLSafeTimedSerializer(app.secret_key, salt="sales-preview").dumps(
                    {"preview": data["preview"], "source": dict(data["source_info"])})
                response.set_data(app.json.dumps(data))
        return response

    # -------------------------------------------------------------------------
    # Rotas do Dashboard
    # -------------------------------------------------------------------------
    @app.route("/")
    def dashboard():
        with _conn() as conn:
            settings = get_settings(conn)
            monitored_stats = count_monitored(conn)
            sales_summary = get_sales_summary(conn)
            recent_events = list_audit_events(conn, limit=6)
        return render_template(
            "dashboard.html",
            settings=settings,
            monitored_stats=monitored_stats,
            sales_summary=sales_summary,
            recent_events=recent_events,
        )

    # -------------------------------------------------------------------------
    # Rotas de Parâmetros
    # -------------------------------------------------------------------------
    @app.route("/parameters")
    def parameters_view():
        with _conn() as conn:
            settings = get_settings(conn)
        return render_template("parameters.html", settings=settings)

    @app.route("/parameters/save", methods=["POST"])
    def parameters_save():
        data = request.form.to_dict()
        # Converter preços em centavos
        try:
            p_min_f = float(data.get("preco_min", "20.00").replace(",", "."))
            p_max_f = float(data.get("preco_max", "1500.00").replace(",", "."))
            data["preco_min_centavos"] = int(p_min_f * 100)
            data["preco_max_centavos"] = int(p_max_f * 100)

            with _conn() as conn:
                update_settings(conn, data)
            flash("Parâmetros de curadoria atualizados e persistidos no SQLite!", "success")
        except Exception as e:
            flash(f"Erro ao salvar parâmetros: {str(e)}", "error")

        return redirect(url_for("parameters_view"))

    # -------------------------------------------------------------------------
    # Rotas de Produtos Monitorados
    # -------------------------------------------------------------------------
    @app.route("/monitored")
    def monitored_view():
        with _conn() as conn:
            products = list_monitored(conn)
            stats = count_monitored(conn)
        return render_template("monitored.html", products=products, stats=stats)

    @app.route("/monitored/add", methods=["POST"])
    def monitored_add():
        titulo = request.form.get("titulo", "")
        url = request.form.get("url", "")
        categoria = request.form.get("categoria", "")
        preco_alvo_str = request.form.get("preco_alvo", "0").replace(",", ".")
        observacoes = request.form.get("observacoes", "")

        try:
            preco_alvo_cents = int(float(preco_alvo_str) * 100)
            with _conn() as conn:
                create_monitored(conn, url, titulo, categoria, preco_alvo_cents, observacoes)
            flash(f"Produto '{titulo}' cadastrado para monitoramento!", "success")
        except sqlite3.IntegrityError:
            flash("Esta URL já está cadastrada no monitoramento.", "warning")
        except Exception as e:
            flash(f"Erro ao cadastrar produto: {str(e)}", "error")

        return redirect(url_for("monitored_view"))

    @app.route("/monitored/<int:product_id>/toggle", methods=["POST"])
    def monitored_toggle(product_id: int):
        with _conn() as conn:
            try:
                new_status = toggle_monitored_status(conn, product_id)
                flash(f"Status do produto alterado para '{new_status}'.", "info")
            except Exception as e:
                flash(f"Erro ao alterar status: {str(e)}", "error")
        return redirect(url_for("monitored_view"))

    @app.route("/monitored/<int:product_id>/delete", methods=["POST"])
    def monitored_delete(product_id: int):
        with _conn() as conn:
            try:
                delete_monitored(conn, product_id)
                flash("Produto monitorado removido com sucesso.", "info")
            except Exception as e:
                flash(f"Erro ao excluir produto: {str(e)}", "error")
        return redirect(url_for("monitored_view"))

    # -------------------------------------------------------------------------
    # Rotas de Vendas e Comissões
    # -------------------------------------------------------------------------
    @app.route("/sales")
    def sales_view():
        status = request.args.get("status", "TODOS")
        tipo = request.args.get("tipo", "TODOS")
        categoria = request.args.get("categoria", "TODAS")
        search = request.args.get("search", "")

        with _conn() as conn:
            sales = list_sales(conn, status=status, tipo=tipo, categoria=categoria, search=search)
            summary = get_sales_summary(conn)
            categories = list_categories(conn)

        return render_template(
            "sales.html",
            sales=sales,
            summary=summary,
            categories=categories,
            current_status=status,
            current_tipo=tipo,
            current_categoria=categoria,
            current_search=search,
        )

    @app.route("/sales/preview-xlsx", methods=["POST"])
    def sales_preview_xlsx():
        if "file" not in request.files:
            return jsonify({"success": False, "error": "Nenhum arquivo enviado."}), 400
        
        file = request.files["file"]
        if not file.filename:
            return jsonify({"success": False, "error": "Nome de arquivo inválido."}), 400

        ano_str = request.form.get("ano", "2026")
        try:
            ano = int(ano_str)
        except ValueError:
            return jsonify({"success": False, "error": "Ano de confirmação inválido."}), 400

        try:
            content_bytes = file.read()
            content_hash = generate_content_hash(content_bytes)
            parsed = parse_xlsx(io.BytesIO(content_bytes), ano)
            with _conn() as conn:
                preview = preview_import(conn, parsed)

            return jsonify({
                "success": True,
                "preview": preview,
                "source_info": {
                    "filename": file.filename,
                    "source_type": "xlsx",
                    "hash": content_hash,
                },
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/sales/preview-sample", methods=["POST"])
    def sales_preview_sample():
        """Lê diretamente a planilha de teste na pasta Relatórios."""
        ano_str = request.form.get("ano", "2026")
        try:
            ano = int(ano_str)
        except ValueError:
            return jsonify({"success": False, "error": "Ano inválido."}), 400

        # Localizar arquivo de teste na pasta
        sample_path = None
        if REPORTS_DIR.exists():
            for f in REPORTS_DIR.iterdir():
                if f.suffix.lower() == ".xlsx" and "esporta" in normalize_text(f.name):
                    sample_path = f
                    break

        if not sample_path or not sample_path.exists():
            return jsonify({"success": False, "error": "Arquivo 'Teste esportação.xlsx' não encontrado na pasta Relatórios."}), 404

        try:
            with open(sample_path, "rb") as f:
                content_bytes = f.read()
            content_hash = generate_content_hash(content_bytes)
            parsed = parse_xlsx(sample_path, ano)
            with _conn() as conn:
                preview = preview_import(conn, parsed)

            return jsonify({
                "success": True,
                "preview": preview,
                "source_info": {
                    "filename": sample_path.name,
                    "source_type": "xlsx",
                    "hash": content_hash,
                },
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/sales/preview-paste", methods=["POST"])
    def sales_preview_paste():
        text = request.form.get("pasted_text", "")
        if not text.strip():
            return jsonify({"success": False, "error": "Nenhum texto informado."}), 400

        ano_str = request.form.get("ano", "2026")
        try:
            ano = int(ano_str)
        except ValueError:
            return jsonify({"success": False, "error": "Ano de confirmação inválido."}), 400

        try:
            content_hash = generate_content_hash(text)
            parsed = parse_pasted_text(text, ano)
            with _conn() as conn:
                preview = preview_import(conn, parsed)

            return jsonify({
                "success": True,
                "preview": preview,
                "source_info": {
                    "filename": f"colagem_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                    "source_type": "paste",
                    "hash": content_hash,
                },
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/sales/confirm-import", methods=["POST"])
    def sales_confirm_import():
        preview_data_raw = request.form.get("preview_data", "")
        source_info_raw = request.form.get("source_info", "")

        if not preview_data_raw or not source_info_raw:
            flash("Dados de confirmação ausentes.", "error")
            return redirect(url_for("sales_view"))

        try:
            preview_data = json.loads(preview_data_raw)
            source_info = json.loads(source_info_raw)
            if cloud:
                from itsdangerous import URLSafeTimedSerializer
                signed = source_info.pop("signature", "")
                verified = URLSafeTimedSerializer(app.secret_key, salt="sales-preview").loads(signed, max_age=600)
                if verified != {"preview": preview_data, "source": source_info}:
                    raise ValueError("A prévia foi alterada. Gere uma nova prévia.")

            with _conn() as conn:
                result = execute_import(
                    conn,
                    parsed_data=preview_data,
                    filename=source_info.get("filename", "desconhecido"),
                    source_type=source_info.get("source_type", "xlsx"),
                    content_hash=source_info.get("hash", ""),
                )

            msg = (
                f"Importação confirmada: {result['novas_vendas']} nova(s) venda(s), "
                f"{result['atualizadas']} status atualizado(s), "
                f"{result['duplicadas_ignoradas']} duplicada(s) ignorada(s)."
            )
            flash(msg, "success")
        except Exception as e:
            flash(f"Falha ao persistir importação: {str(e)}", "error")

        return redirect(url_for("sales_view"))

    @app.route("/sales/<int:sale_id>/status", methods=["POST"])
    def sales_update_status(sale_id: int):
        new_status = request.form.get("status", "")
        with _conn() as conn:
            try:
                update_sale_status(
                    conn,
                    sale_id=sale_id,
                    new_status=new_status,
                    observacao="Alteração manual via painel",
                )
                flash(f"Status da venda #{sale_id} alterado para '{new_status}'.", "info")
            except Exception as e:
                flash(f"Erro ao alterar status: {str(e)}", "error")
        return redirect(url_for("sales_view"))

    # -------------------------------------------------------------------------
    # Rotas de Diagnóstico e Backup
    # -------------------------------------------------------------------------
    @app.route("/diagnostics")
    def diagnostics_view():
        if cloud:
            with _conn() as conn:
                size = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
                return render_template("diagnostics.html", app_version=APP_VERSION, sqlite_version="",
                    db_path="PostgreSQL remoto", db_size_formatted=f"{size/1024:.1f} KB", backups=[],
                    imports_list=list_imports(conn,limit=20),audit_events=list_audit_events(conn,limit=30))
        db_file = Path(app.config.get("DB_PATH", DB_PATH))
        with _conn() as conn:
            backups = list_backups(db_file.parent / "backups")
            imports_list = list_imports(conn, limit=20)
            audit_events = list_audit_events(conn, limit=30)
            sqlite_version = conn.execute("SELECT sqlite_version()").fetchone()[0]

        db_file = Path(app.config.get("DB_PATH", DB_PATH))
        db_size_bytes = db_file.stat().st_size if db_file.exists() else 0
        db_size_formatted = f"{db_size_bytes / 1024:.1f} KB"

        return render_template(
            "diagnostics.html",
            app_version=APP_VERSION,
            sqlite_version=sqlite_version,
            db_path=str(db_file),
            db_size_formatted=db_size_formatted,
            backups=backups,
            imports_list=imports_list,
            audit_events=audit_events,
        )

    @app.route("/diagnostics/backup", methods=["POST"])
    def diagnostics_backup():
        if cloud:
            from services.hosted_backup import export_snapshot
            from flask import send_file
            content = export_snapshot(db_file)
            return send_file(io.BytesIO(content),mimetype="application/json",as_attachment=True,
                download_name="basetrilheiros-backup.json")
        try:
            local_db_file = Path(app.config.get("DB_PATH", DB_PATH))
            res = create_backup(local_db_file, local_db_file.parent / "backups")
            flash(f"Backup gerado com sucesso: {res['filename']} ({res['size_formatted']})", "success")
        except Exception as e:
            flash(f"Erro ao criar backup: {str(e)}", "error")
        return redirect(url_for("diagnostics_view"))

    return app


