"""Protect the local data directory using POSIX modes or Windows user ACLs."""
import os
from pathlib import Path
import re
import subprocess


def secure_data_directory(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        directory.chmod(0o700)
        return
    result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                            capture_output=True, text=True, check=True)
    match = re.search(r"S-1-(?:\d+-)*\d+", result.stdout)
    if not match:
        raise RuntimeError("Não foi possível identificar o usuário Windows para proteger os dados.")
    sid = match.group()
    result = subprocess.run([
        "icacls", str(directory), "/inheritance:r", "/grant:r",
        f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F",
    ], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Não foi possível proteger app/data. Use uma pasta local NTFS do seu usuário.")
