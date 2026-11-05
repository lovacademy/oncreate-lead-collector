# OnCreate Public Healthcare Collector

Coletor independente de organizações de saúde americanas, preparado para ser colocado na **raiz de um novo repositório público**. O CRM completo deve permanecer privado.

## Fontes

- CMS/NPPES NPI-2: organizações de saúde por especialidade, NPI, cidade e estado, sem API key.
- Tavily Search: opcional, pesquisa o site oficial do negócio e procura e-mails comerciais publicados como `mailto:`. Plano Researcher gratuito atualmente inclui 1.000 créditos/mês. O código limita pesquisas a até 15 por execução diária.
- Apollo Organization Search: **desativado**, porque exige um plano que não está disponível.
- Zocdoc, Tebra, diretórios AMA e resultados HTML do Google: **não coletados** por este sistema.

Não envia e-mails, não consulta dados de pacientes, não considera um endereço público como autorização para marketing. Usa sites HTTPS, bloqueio de domínios restritos, verificação de robots, verificação de DNS público, limite de requisições, sem redirects.

## Colocar em funcionamento

1. Repositório público criado: https://github.com/lovacademy/oncreate-lead-collector. O CRM `lovacademy/oncreate-ai-calling` permanece privado.
2. Os arquivos desta pasta já estão publicados na raiz deste repositório, preservando `.github/workflows/collect.yml`, `scripts/run_daily.py`, `scripts/daily_lead_discovery.py` e `scripts/test_discovery.py`.
3. Gerar um token secreto aleatório no Mac com `openssl rand -hex 32`.
4. Salvar token em **Supabase > Edge Functions > Secrets > ONCREATE_DISCOVERY_INGEST_TOKEN**.
5. Em **novo GitHub repo > Settings > Secrets and variables > Actions**:
   - Variable `ONCREATE_INGEST_URL` = `https://bolslnqrinkeeqpjwkdr.supabase.co/functions/v1/oncreate-lead-ingest`
   - Secret `ONCREATE_INGEST_TOKEN` = mesmo token do Supabase
   - Secret opcional `TAVILY_API_KEY` = chave da API Tavily gratuita
6. Rodar Actions > **OnCreate Public Healthcare Discovery** > Run workflow e inspecionar candidatos no Supabase/CRM.

**Nunca colocar uma chave Supabase service_role no repo público.** A Edge Function recebe apenas candidatos e faz validação de campos.

## Limites e operação

O job diário é agendado às 11:15 UTC; tempo máximo do job 350 minutos, pesquisa encerrada em até 340 minutos. O script pode terminar antes ao esgotar especialidades, estados ou limites. Runners padrão de GitHub Actions em repositórios públicos são gratuitos dentro das políticas do GitHub; o uso de APIs privadas e outras contas segue suas próprias cotas.

Atenção: sem Tavily (ou outra fonte aprovada de sites oficiais), os registros NPPES geralmente ficam **sem website e sem e-mail**.


## Atualização: captura de contatos com evidência (05/11/2026)

O crawler agora verifica **até sete páginas** do site de cada empresa (home, contato, equipe/profissionais, localização e páginas públicas relacionadas, quando permitidas). Examina somente endereços comerciais publicados em `mailto:`, texto visível e JSON-LD, sem inferir endereços.

No Supabase, cada registro carrega: `website`, `business_email`, `email_source_url`, `email_source_type`, `email_confidence` (heurística 0–100), `site_confidence`, `crawl_status`, `pages_scanned` e `last_crawled_at`. Pontuação alta **não equivale a validade de entrega nem autorização**. O sistema mantém o melhor endereço encontrado quando uma nova execução não localiza outro.

### Configuração atual do repositório público

O diagnóstico do GitHub Actions identificou que os campos **ainda não foram configurados neste repositório público** (podem estar no privado):

- **Settings → Secrets and variables → Actions → Secrets:** `TAVILY_API_KEY` e `ONCREATE_INGEST_TOKEN`
- **Settings → Secrets and variables → Actions → Variables:** `ONCREATE_INGEST_URL` = `https://bolslnqrinkeeqpjwkdr.supabase.co/functions/v1/oncreate-lead-ingest`
- O token `ONCREATE_INGEST_TOKEN` precisa ter o **mesmo valor** no Supabase > Edge Functions > Secrets > `ONCREATE_DISCOVERY_INGEST_TOKEN`. Gere um token aleatório de 32+ caracteres.

**Não coloque `LEAD_SUPABASE_SERVICE_ROLE_KEY` neste repositório.** Enquanto faltar a variável ou o token, o workflow diário não conseguirá gravar candidatos no Supabase.

Links: `Actions > First Email Discovery Verification` para testar com até 3 buscas da Tavily e `Actions > OnCreate Public Healthcare Discovery` para a rotina diária.
