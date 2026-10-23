# Hospedagem do painel

O modo online usa Render para Python e Neon para PostgreSQL. O site institucional no GitHub Pages permanece separado. A implantação ainda depende de contas e da configuração dos segredos no provedor.

## Limites gratuitos

O Render gratuito suspende o serviço após 15 minutos sem tráfego; o primeiro acesso pode demorar. Há uma franquia compartilhada de 750 horas por mês. Portanto esta opção atende ao painel e às consultas manuais, mas não mantém um robô de fundo funcionando continuamente. O Neon possui cotas de armazenamento e processamento; confira o plano antes da criação. Não habilite cobrança automática sem necessidade.

Referências: https://render.com/docs/free e https://neon.com/pricing.

## Preparar as contas e publicar

1. Crie suas contas em https://render.com e https://neon.com. Senhas, consentimentos e eventuais verificações são feitos pelo proprietário.
2. No Neon, crie um projeto PostgreSQL e copie a conexão somente para a configuração privada do Render. Utilize `sslmode=verify-full&sslrootcert=system` na conexão; nunca publique a URL no GitHub.
3. No Render, conecte o repositório e use o Blueprint `render.yaml`. A configuração aponta para a branch de hospedagem. Revise o plano gratuito antes de criar o serviço.
4. Preencha `DATABASE_URL` e `ADMIN_PASSWORD_HASH`. Execute localmente `python scripts/password_hash.py` para criar o hash de uma senha de pelo menos 14 caracteres. Guarde a senha em seu gerenciador de senhas. O usuário inicial é `admin`.
5. As variáveis `BASETRILHEIROS_SECRET_KEY` e `BASETRILHEIROS_MASTER_SECRET` são geradas pelo provedor. Guarde cópias privadas e mantenha os valores entre publicações: trocar a segunda impede decifrar credenciais já armazenadas. Nenhum segredo pertence ao repositório.
6. O endereço HTTPS é obtido de `RENDER_EXTERNAL_URL`. Para domínio personalizado, configure também `PUBLIC_BASE_URL` com a origem HTTPS exata, sem caminho, e configure o domínio no provedor.
7. Abra o endereço publicado, entre com sua senha e verifique os diagnósticos.

## Mercado Livre

Cadastre no DevCenter o retorno exato `https://ENDERECO-DO-PAINEL/ml/callback`, sem barra final. Informe App ID e Client Secret no painel autenticado, conecte a conta e aceite o consentimento no Mercado Livre. A versão online recebe o retorno diretamente; não precisa da ponte estática de retorno local.

Valide uma consulta real no painel. A implementação de OAuth foi testada com respostas simuladas; a API pode negar a pesquisa conforme as permissões da aplicação. Publicar o painel não concede permissões adicionais nem implementa monitoramento ou envio automático.

## Dados existentes e cópias

Uma instalação nova começa vazia. O script `scripts/migrate_business_data.py --source CAMINHO-DO-SQLITE --confirm` copia dados comerciais de um SQLite aberto somente para leitura para um PostgreSQL vazio, indicado por `DATABASE_URL`. Ele verifica contagens e total de comissões dentro de transação; recusa mesclar com uma instalação já preenchida. Não transfere credenciais do Mercado Livre: conecte a conta novamente no painel online. Preserve o arquivo SQLite e sua cópia antes da migração.

Em Diagnósticos, o modo online oferece download de uma cópia lógica JSON consistente, com credenciais ainda cifradas. Guarde-a em local privado e preserve a chave mestra separadamente. Esse arquivo não é uma cópia física PostgreSQL nem possui importação automática pelo painel; para recuperação completa use também as ferramentas de exportação/restauração do provedor.

## Segurança e execução

Todo acesso comercial exige login. Formulários usam proteção CSRF; prévias de importação são assinadas e expiram. O serviço valida origem HTTPS e domínio, cifra credenciais e utiliza Gunicorn, sem publicar o servidor Windows. `/healthz` é público e retorna somente o estado do processo. A validação da publicação deve incluir login, persistência após reinício, consulta real e cópia de segurança.

O erro SSL do pip no Windows não deve ser contornado desabilitando a verificação. A construção no Render usa seu próprio ambiente; a conexão com o Neon exige TLS verificado. Ajuste a confiança legítima da rede local caso continue instalando no Windows.
