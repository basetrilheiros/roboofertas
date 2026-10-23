"""
Configurações da aplicação Base Trilheiros (Fase 1).
Aplicação 100% local, vinculada estritamente a 127.0.0.1.
"""
from pathlib import Path
import os

# Caminhos base da aplicação
APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DATA_DIR = Path(os.environ.get("BASETRILHEIROS_DATA_DIR", APP_DIR / "data"))
from services.local_permissions import secure_data_directory
secure_data_directory(DATA_DIR)

DB_PATH = DATA_DIR / "basetrilheiros.db"
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

LOGS_DIR = APP_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Pasta de relatórios original preservada
REPORTS_DIR = PROJECT_DIR / "Relatorios"

# Configurações do servidor web local
HOST = "127.0.0.1"  # Nunca expor em 0.0.0.0
PORT = int(os.environ.get("BASETRILHEIROS_PORT", 5000))
DEBUG = os.environ.get("BASETRILHEIROS_DEBUG", "0") == "1"
SECRET_KEY = os.environ.get("BASETRILHEIROS_SECRET_KEY", "basetrilheiros-local-secret-phase1")

# Fuso horário padrão
TIMEZONE = "America/Sao_Paulo"
SCHEDULED_TIME = "08:00"

# Metadados do sistema
APP_NAME = "Base Trilheiros — Robô de Ofertas e Comissões"
APP_VERSION = "2.1-A Windows — repasse 22/10/2026"
