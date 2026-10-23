# Base Trilheiros — Robô de Ofertas

Aplicação Python para gestão local de vendas e comissões de afiliados, cadastro de produtos, configuração OAuth do Mercado Livre e consulta manual de anúncios.

## Estado atual

- Painel Flask/Jinja com SQLite local e HTTPS em `https://127.0.0.1:5000`.
- Importação XLSX/texto, prévia, deduplicação e histórico de status.
- Parâmetros comerciais e produtos cadastrados para monitoramento futuro.
- Autorização OAuth com PKCE, state de uso único, sessão e tokens cifrados com Fernet.
- Renovação no momento da consulta e busca manual de até 20 anúncios, verificando a conta antes da busca.
- Página estática de retorno público em `public-callback/ml/callback/`.

A implementação foi testada com respostas simuladas. Na criação deste repositório, a conta real ainda não havia concluído o consentimento e a busca real não havia sido validada. A disponibilidade da busca depende do acesso que o Mercado Livre permitir à aplicação. Não há curadoria automática, agendador, envio de WhatsApp ou comprovação de desconto histórico.

## Instalação Windows

O modo online em preparação utiliza login obrigatório, PostgreSQL no Neon e aplicação no Render. Consulte [Hospedagem](docs/HOSPEDAGEM.md) para configuração, migração e limites gratuitos. A publicação e a conexão real ainda precisam ser validadas no provedor.

Requisitos desta versão: Windows 64 bits e Python 3.11 ou 3.12 de 64 bits, com launcher `py` ou Python no PATH.

1. Clone ou extraia o projeto em pasta local gravável.
2. Execute `1_INSTALAR.bat`: cria ambiente, instala dependências e prepara apenas o esquema de um banco vazio quando não existe banco.
3. Execute `2_ABRIR.bat` para o modo local sem integração real.
4. Para conexão e buscas manuais, encerre a instância aberta com `3_ENCERRAR.bat` e execute `6_CONECTAR_MERCADO_LIVRE.bat`.
5. Use `4_DIAGNOSTICO.bat` para verificar componentes/banco e `5_TESTAR.bat` para os testes.

O certificado HTTPS é gerado localmente. Não é instalada confiança global no Windows. A aplicação não deve ser publicada ou escutar em interfaces públicas.

Se pip falhar com `CERTIFICATE_VERIFY_FAILED`, confirme a autoridade certificadora legítima da rede. Em pip 22.2–24.1/Python >=3.10, `--use-feature=truststore` pode usar a confiança do sistema; em pip >=24.2 esse comportamento é padrão. Não use `--trusted-host` ou desative TLS.

## Conectar ao Mercado Livre

1. Publique somente `public-callback/ml/callback/` no site estático de sua confiança. No site Base Trilheiros, o retorno publicado é `https://basetrilheiros.com.br/ml/callback/`.
2. Cadastre exatamente o mesmo Redirect URI no DevCenter e no painel local, incluindo barra final.
3. Informe App ID e Client Secret diretamente no painel; não coloque segredos no código ou no Git.
4. Clique em Conectar minha conta e revise/aceite o consentimento na plataforma.
5. No retorno público, volte ao painel no mesmo navegador/computador e conclua a conexão.
6. Execute uma busca manual. Um 403 na busca não significa necessariamente falha no OAuth.

O retorno público recebe código temporário e state; não recebe Client Secret, tokens permanentes ou banco. Ele remove parâmetros da barra e retorna ao loopback por fragmento. A hospedagem/CDN integra a cadeia de confiança e pode registrar a URL inicial. Não adicione analytics ou scripts de terceiros nessa página.

O diretório `public-callback` é apenas a fonte da página: este repositório não tem publicação automática configurada. A aplicação local continua separada do site institucional.

## Estrutura

- `app/web/`: rotas, templates e arquivos estáticos.
- `app/services/`: importação, OAuth, criptografia, API, TLS, backup e permissões.
- `app/models/`: acesso SQL dos módulos de negócio.
- `app/database/`: conexão, esquema e migrações.
- `app/tests/`: testes e fixture exclusivamente sintética.
- `windows/`: inicialização, verificação e encerramento autenticado.
- `public-callback/`: página pública de retorno para a autorização.

## Dados, backup e segurança

Não são versionados `app/data`, bancos SQLite, chaves, tokens, certificados, relatórios comerciais, logs, backups ou ambientes virtuais. A fixture XLSX incluída foi gerada com produtos, lojas e identificadores fictícios. Não há vendas pré-carregadas numa instalação nova.

Antes de atualizar a instalação com dados reais, encerre o servidor e preserve `app/data` inteira, mantendo banco e chave juntos. O backup pelo painel copia apenas o banco e não substitui esse backup integral. Não copie a pasta de dados para o repositório.

O servidor é de uso local. A suíte não equivale a uma auditoria de segurança nem à validação de permissões reais da plataforma. Algumas limitações existentes: importação confirma JSON enviado pelo navegador; deduplicação não reconcilia correções de valores; vendas têm listagem limitada a 100 itens; monitorados ainda não consultam preços periodicamente. Proteção CSRF das operações comerciais é aplicada no modo real.

## Testes

Na pasta `app`, execute `.venv\Scripts\python.exe -m pytest -q`. Os testes criam bancos temporários e bloqueiam chamadas HTTP reais por `requests`.

O teste opcional de servidor HTTPS pode ser habilitado com `BASETRILHEIROS_TESTAR_HTTPS_LOCAL=1`, apenas para execução local. Os testes de ACL exigem Windows. Python 3.12 pode emitir avisos sobre conversores timestamp do SQLite.

## Fontes oficiais

- [Autenticação Mercado Livre](https://developers.mercadolivre.com.br/autenticacao-e-autorizacao)
- [Certificados HTTPS do pip](https://pip.pypa.io/en/stable/topics/https-certificates/)
