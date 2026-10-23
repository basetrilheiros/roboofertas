#!/usr/bin/env python3
"""
Ponto de entrada para execução local do Base Trilheiros (Fase 1).
Uso:
    python run.py
"""
import sys
import os
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

# Adiciona o diretório da aplicação ao sys.path
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from config import APP_NAME, APP_VERSION, HOST, PORT
from web.app import create_app

if __name__ == "__main__":
    print("=" * 70)
    print(f"🌲 {APP_NAME} — {APP_VERSION}")
    print(f"📍 Servidor Web Local: https://{HOST}:{PORT}")
    print(f"🔒 100% Local em 127.0.0.1 (Sem exposição na rede)")
    print("=" * 70)
    
    # A shared installation starts offline; live authorization is a separate decision.
    app = create_app({"ML_REAL_OAUTH_ENABLED": os.environ.get("BASETRILHEIROS_OAUTH_REAL", "0") == "1"})
    from services.local_tls import ensure_local_tls
    import logging
    # Callback query strings can contain authorization codes: suppress access logging.
    logging.getLogger("werkzeug").disabled = True
    app.run(host=HOST, port=PORT, debug=False, ssl_context=ensure_local_tls())
