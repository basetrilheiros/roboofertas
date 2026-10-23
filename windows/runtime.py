"""Portable local control; no OS-wide process termination or public listener."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def exclusive_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("Outra execução já está em andamento nesta instalação.") from None
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError("Outra execução já está em andamento nesta instalação.") from None
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


class Runtime:
    def __init__(self, root=ROOT, port=5000):
        self.root = Path(root).resolve()
        self.app = self.root / "app"
        self.port = port
        self.url = f"https://127.0.0.1:{port}"
        self.data = self.app / "data"
        self.control_file = self.data / ".windows_control.json"
        self.identifier = hashlib.sha256(str(self.root).encode()).hexdigest()

    def opener(self):
        context = ssl.create_default_context(cafile=str(self.data / "tls/localhost.crt"))
        return urllib.request.build_opener(urllib.request.ProxyHandler({}),
                    urllib.request.HTTPSHandler(context=context))

    def status(self):
        try:
            with self.opener().open(self.url + "/__local/health", timeout=2) as response:
                value = json.load(response)
            return value.get("installation") == self.identifier
        except (OSError, ValueError, urllib.error.URLError):
            return False

    def port_busy(self):
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                return True
        except OSError:
            return False

    def start(self):
        if self.status():
            self.open_browser()
            return
        if self.port_busy():
            raise RuntimeError("A porta 5000 está ocupada. Encerre a execução anterior pelo seu próprio atalho; nenhum processo foi alterado.")
        python = self.app / ".venv/Scripts/python.exe"
        if not python.is_file():
            raise RuntimeError("Execute primeiro 1_INSTALAR.bat.")
        environment = dict(os.environ)
        environment["BASETRILHEIROS_DATA_DIR"] = str(self.data)
        environment["BASETRILHEIROS_PORT"] = str(self.port)
        environment["BASETRILHEIROS_OAUTH_REAL"] = os.environ.get("BASETRILHEIROS_OAUTH_REAL", "0")
        environment["PYTHONUTF8"] = "1"
        options = {"creationflags": subprocess.CREATE_NEW_CONSOLE} if os.name == "nt" else {"start_new_session": True}
        child = subprocess.Popen([str(python), str(self.root / "windows/servidor.py")],
                                 cwd=self.root, env=environment, **options)
        for _ in range(40):
            if self.status():
                self.open_browser()
                return
            if child.poll() is not None:
                raise RuntimeError("O servidor encerrou. Consulte a mensagem da janela do servidor ou execute 4_DIAGNOSTICO.bat.")
            time.sleep(0.5)
        raise RuntimeError("O servidor ainda não respondeu. Confira sua janela antes de tentar abrir novamente.")

    def open_browser(self):
        if not webbrowser.open(self.url + "/mercado-livre"):
            print("Abra no navegador: " + self.url)
        print("Base Trilheiros disponível. Use 3_ENCERRAR.bat para encerrar.")

    def stop(self):
        if not self.status():
            if self.port_busy():
                raise RuntimeError("A porta está ocupada por uma execução que este atalho não reconhece. Nada foi encerrado.")
            print("O Base Trilheiros já está encerrado.")
            return
        try:
            token = json.loads(self.control_file.read_text(encoding="utf-8"))["token"]
        except (OSError, ValueError, KeyError):
            raise RuntimeError("Não encontrei o controle desta execução. Feche apenas a janela do servidor desta instalação.") from None
        request = urllib.request.Request(self.url + "/__local/stop", data=b"",
                                        headers={"X-Local-Control": token}, method="POST")
        try:
            with self.opener().open(request, timeout=4) as response:
                if response.status != 200:
                    raise RuntimeError("O servidor não confirmou o encerramento.")
        except urllib.error.HTTPError:
            raise RuntimeError("O controle desta execução não foi aceito. Nenhum processo foi forçado a encerrar.") from None
        except (OSError, urllib.error.URLError):
            if self.status():
                raise RuntimeError("Não foi possível enviar o pedido de encerramento.") from None
        for _ in range(40):
            if not self.status() and not self.port_busy():
                print("Base Trilheiros encerrado. Dados salvos na pasta app/data.")
                return
            time.sleep(0.25)
        raise RuntimeError("O encerramento ainda não concluiu. Não foi usado encerramento forçado.")

    def verify(self):
        import sqlite3
        import struct
        if not (3, 11) <= sys.version_info[:2] <= (3, 12) or struct.calcsize("P") != 8:
            raise RuntimeError("Use Python 3.11 ou 3.12 de 64 bits nesta versão.")
        if sqlite3.sqlite_version_info < (3, 35):
            raise RuntimeError("Esta versão do SQLite é antiga. Reinstale o Python indicado no guia.")
        for name in ("flask", "requests", "cryptography", "openpyxl", "pytest"):
            __import__(name)
        sys.path.insert(0, str(self.app))
        from services.local_permissions import secure_data_directory
        secure_data_directory(self.data)
        path = self.data / "basetrilheiros.db"
        if not path.is_file():
            raise RuntimeError("Não encontrei o banco incluído no pacote. Extraia o ZIP inteiro em uma pasta nova.")
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("O banco não passou na verificação. Preserve a pasta atual e extraia novamente em outra pasta.")
            sales = connection.execute("SELECT count(*) FROM sales").fetchone()[0]
            monitored = connection.execute("SELECT count(*) FROM monitored_products").fetchone()[0]
        finally:
            connection.close()
        print(f"Python e componentes disponíveis. Banco íntegro: {sales} vendas, {monitored} monitorado(s).")
        print("Nenhuma credencial foi exibida e nenhuma consulta ao Mercado Livre foi realizada.")


def main():
    runtime = Runtime()
    if len(sys.argv) != 2 or sys.argv[1] not in ("abrir", "encerrar", "verificar"):
        raise RuntimeError("Ação inválida. Use os arquivos .bat do pacote.")
    if sys.argv[1] == "verificar":
        runtime.verify()
    else:
        with exclusive_lock(runtime.data / ".windows_launcher.lock"):
            (runtime.start if sys.argv[1] == "abrir" else runtime.stop)()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Não foi possível concluir: " + str(error))
        sys.exit(1)
