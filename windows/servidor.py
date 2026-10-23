"""Run the application locally with authenticated, installation-specific shutdown."""
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import threading

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))
from runtime import Runtime, exclusive_lock


def serve():
    from config import DATA_DIR, PORT
    from services.local_tls import ensure_local_tls
    from web.app import create_app
    from flask import jsonify, request
    from werkzeug.serving import make_server
    runtime = Runtime(ROOT, PORT)
    if DATA_DIR.resolve() != runtime.data.resolve():
        raise RuntimeError("A execução Windows deve usar os dados desta instalação.")
    with exclusive_lock(DATA_DIR / ".windows_server.lock"):
        logging.getLogger("werkzeug").disabled = True
        # Handoff defaults to offline mode; activation is a later, explicit decision.
        app = create_app({"ML_REAL_OAUTH_ENABLED": os.environ.get("BASETRILHEIROS_OAUTH_REAL", "0") == "1"})
        token = secrets.token_urlsafe(48)

        @app.get("/__local/health")
        def local_health():
            response = jsonify(installation=runtime.identifier)
            response.headers["Cache-Control"] = "no-store"
            return response

        @app.post("/__local/stop")
        def local_stop():
            candidate = request.headers.get("X-Local-Control", "")
            if not hmac.compare_digest(candidate.encode(), token.encode()):
                return jsonify(error="Controle local obrigatório."), 403
            threading.Thread(target=server.shutdown, daemon=True).start()
            return jsonify(status="encerrando")

        server = make_server("127.0.0.1", PORT, app, threaded=True,
                             ssl_context=ensure_local_tls())
        temporary = runtime.control_file.with_suffix(".tmp")
        temporary.write_text(json.dumps({"token": token}), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, runtime.control_file)
        print("Base Trilheiros iniciado em " + runtime.url, flush=True)
        print("Mantenha esta janela aberta. Para encerrar, use 3_ENCERRAR.bat.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            runtime.control_file.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        serve()
    except Exception:
        # Never print a traceback that might contain callback URLs or credentials.
        print("O servidor não iniciou ou foi interrompido. Confira 4_DIAGNOSTICO.bat e se a porta 5000 está livre.", flush=True)
        sys.exit(1)
