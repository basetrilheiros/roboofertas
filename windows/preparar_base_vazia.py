"""Create only the schema for a new source checkout; preserve existing databases."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
from config import DB_PATH
from database.migrations import ensure_database
from services.security_migration import migrate_security
if not DB_PATH.exists():
    ensure_database(DB_PATH)
    migrate_security(DB_PATH)
    print("Base vazia criada. Nenhum dado comercial foi incluído.")
else:
    print("Base existente preservada.")
