import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from unittest.mock import Mock
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("windows_runtime", ROOT / "windows/runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def test_runtime_does_not_start_second_server(tmp_path, monkeypatch):
    value = runtime.Runtime(tmp_path)
    monkeypatch.setattr(value, "status", lambda: True)
    browser = Mock()
    monkeypatch.setattr(value, "open_browser", browser)
    spawn = Mock()
    monkeypatch.setattr(runtime.subprocess, "Popen", spawn)
    value.start()
    browser.assert_called_once()
    spawn.assert_not_called()


def test_runtime_refuses_unknown_listener(tmp_path, monkeypatch):
    value = runtime.Runtime(tmp_path)
    monkeypatch.setattr(value, "status", lambda: False)
    monkeypatch.setattr(value, "port_busy", lambda: True)
    spawn = Mock()
    monkeypatch.setattr(runtime.subprocess, "Popen", spawn)
    with pytest.raises(RuntimeError, match="ocupada"):
        value.start()
    with pytest.raises(RuntimeError, match="não reconhece"):
        value.stop()
    spawn.assert_not_called()


def test_control_token_is_required(tmp_path, monkeypatch):
    value = runtime.Runtime(tmp_path)
    monkeypatch.setattr(value, "status", lambda: True)
    with pytest.raises(RuntimeError, match="controle"):
        value.stop()


def test_lock_prevents_duplicate_launcher(tmp_path):
    lock = tmp_path / "lock"
    with runtime.exclusive_lock(lock):
        with pytest.raises(RuntimeError):
            with runtime.exclusive_lock(lock):
                pass
    with runtime.exclusive_lock(lock):
        pass


def test_batch_files_have_quoted_paths_and_crlf():
    for name in ("1_INSTALAR.bat", "2_ABRIR.bat", "3_ENCERRAR.bat", "4_DIAGNOSTICO.bat", "5_TESTAR.bat"):
        data = (ROOT / name).read_bytes()
        assert b"\r\n" in data
        assert b'cd /d "%~dp0' in data
        assert b"taskkill" not in data.lower()
        assert b"executionpolicy" not in data.lower()
        assert b"certutil" not in data.lower()


def test_permission_helper_restricts_posix_directory(tmp_path):
    from services.local_permissions import secure_data_directory
    directory = tmp_path / "private"
    secure_data_directory(directory)
    if os.name != "nt":
        assert directory.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(os.name != "nt", reason="A validação de ACLs requer Windows real.")
def test_windows_private_directory_has_no_inherited_acl(tmp_path):
    from services.local_permissions import secure_data_directory
    directory = tmp_path / "private"
    secure_data_directory(directory)
    result = subprocess.run(["icacls", str(directory)], capture_output=True, text=True, check=True)
    assert "(I)" not in result.stdout


@pytest.mark.skipif(os.environ.get("BASETRILHEIROS_TESTAR_HTTPS_LOCAL") != "1",
                    reason="Teste de servidor real é executado separadamente, só no loopback.")
def test_https_server_and_authenticated_shutdown(tmp_path):
    # Entirely disposable application; never use the distributable snapshot during tests.
    root = tmp_path / "Instalacao com espacos"
    shutil.copytree(ROOT / "app", root / "app",
                    ignore=shutil.ignore_patterns("data", "logs", "__pycache__", ".pytest_cache", ".venv"))
    shutil.copytree(ROOT / "windows", root / "windows", ignore=shutil.ignore_patterns("__pycache__"))
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        port = candidate.getsockname()[1]
    value = runtime.Runtime(root, port)
    environment = dict(os.environ)
    environment.update(BASETRILHEIROS_DATA_DIR=str(value.data), BASETRILHEIROS_PORT=str(port), PYTHONUTF8="1")
    child = subprocess.Popen([sys.executable, str(root / "windows/servidor.py")],
                             cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(40):
            if value.status():
                break
            if child.poll() is not None:
                pytest.fail("Servidor não iniciou na cópia descartável.")
            time.sleep(0.25)
        assert value.status()
        with value.opener().open(value.url + "/mercado-livre", timeout=3) as page:
            html = page.read().decode()
            assert "Testar conexão simulada" in html
            assert "Conectar minha conta" not in html
        request = runtime.urllib.request.Request(value.url + "/__local/stop", data=b"", method="POST")
        with pytest.raises(runtime.urllib.error.HTTPError) as error:
            value.opener().open(request, timeout=3)
        assert error.value.code == 403
        assert value.status()
        value.stop()
        assert child.wait(timeout=5) == 0
        assert not value.control_file.exists()
        assert not value.status()
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
        if child.stdout:
            child.stdout.close()
