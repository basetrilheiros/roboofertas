# Contribuindo

Não faça commit de dados reais, tokens, Client Secret, chaves, certificados, relatórios ou backups. Use apenas dados fictícios nos testes.

Faça alterações e testes em uma cópia de desenvolvimento com banco temporário. Não execute testes contra a instalação comercial.

Antes de publicar, examine `git status`, o conteúdo preparado para commit e as regras de `.gitignore`. Nunca use `git add -f` para incluir pastas privadas. Não publique um arquivo `.env` preenchido.

Uma correção de código não comprova conectividade ou permissão na API. Registre separadamente testes simulados, testes locais e validação real autorizada.
