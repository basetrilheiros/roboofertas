"""
Testes unitários do módulo de criptografia e proteção de credenciais em repouso.
"""
import os
from pathlib import Path
import stat
import tempfile
import pytest

from services.crypto import decrypt_secret, encrypt_secret, get_or_create_master_key


def test_crypto_roundtrip(tmp_path):
    """Valida ciclo completo de encriptação e decriptação com segredos reais."""
    if True:
        key_file = tmp_path / "test.key"
        plaintext = "segredo_super_confidencial_ml_123456"

        ciphertext = encrypt_secret(plaintext, key_file=key_file)
        assert ciphertext is not None
        # O texto cifrado versionado não deve conter o segredo original
        assert plaintext not in ciphertext
        assert len(ciphertext) >= 48 * 2  # nonce (16) + tag (32) + dados

        decrypted = decrypt_secret(ciphertext, key_file=key_file)
        assert decrypted == plaintext


def test_crypto_tampering_detection(tmp_path):
    """Valida que qualquer alteração indevida no texto cifrado é rejeitada."""
    if True:
        key_file = tmp_path / "test.key"
        ciphertext = encrypt_secret("token_de_teste", key_file=key_file)
        
        # Corrompe o último caractere do ciphertext
        tampered = ciphertext[:-2] + ("00" if ciphertext[-2:] != "00" else "ff")
        with pytest.raises(ValueError, match="autenticação do segredo"):
            decrypt_secret(tampered, key_file=key_file)


def test_master_key_file_permissions():
    """Valida que o arquivo da chave mestra é criado com permissão 0600 (apenas proprietário)."""
    with tempfile.TemporaryDirectory() as td:
        key_path = Path(td) / ".app_secret_key"
        get_or_create_master_key(key_file=key_path)

        assert key_path.exists()
        file_mode = stat.S_IMODE(os.stat(key_path).st_mode)
        assert file_mode == 0o600 if os.name != "nt" else file_mode & stat.S_IWRITE
