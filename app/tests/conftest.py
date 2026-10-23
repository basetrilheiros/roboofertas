"""
Configurações e fixtures para o pytest.
"""
from pathlib import Path
import os
import atexit
import shutil

import tempfile
import pytest

_TEST_DATA = tempfile.mkdtemp(prefix="basetrilheiros-tests-")
os.environ["BASETRILHEIROS_DATA_DIR"] = _TEST_DATA
atexit.register(shutil.rmtree, _TEST_DATA, ignore_errors=True)

from database.connection import get_db, init_db
from database.migrations import ensure_database
from web.app import create_app

SAMPLE_XLSX_PATH = Path(__file__).parent / "fixtures" / "sample.xlsx"


@pytest.fixture
def temp_db():
    """Cria um banco de dados temporário para cada teste."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = Path(tf.name)
    
    ensure_database(db_path)
    yield db_path
    
    # Limpeza
    try:
        db_path.unlink(missing_ok=True)
        # remover arquivos wal e shm se existirem
        Path(f"{db_path}-wal").unlink(missing_ok=True)
        Path(f"{db_path}-shm").unlink(missing_ok=True)
    except OSError:
        pass


@pytest.fixture
def client(temp_db):
    """Cria um cliente de teste do Flask com banco isolado."""
    app = create_app({"TESTING": True, "DB_PATH": temp_db})
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def block_real_http(monkeypatch):
    import requests
    def blocked(*args, **kwargs):
        raise AssertionError("Rede real proibida nos testes")
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
