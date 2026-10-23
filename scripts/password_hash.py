"""Print only a password hash for the hosting secret field; never echo the password."""
from getpass import getpass
from werkzeug.security import generate_password_hash
password=getpass('Senha do painel (pelo menos 14 caracteres): ')
confirm=getpass('Repita a senha: ')
if len(password)<14 or password!=confirm: raise SystemExit('Senha curta ou confirmação diferente.')
print(generate_password_hash(password,method='pbkdf2:sha256:600000'))
