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


## Operação noturna autenticada (novembro de 2026)

A coleta funciona **sem chave administrativa do Supabase no repositório público**. O workflow concede apenas `id-token: write`, solicita um token OIDC assinado pelo GitHub Actions e a Edge Function confere assinatura RSA, público-alvo, repositório, IDs imutáveis e branch `main`. `ONCREATE_INGEST_TOKEN` é um fallback legado, não é mais obrigatório para execuções via GitHub Actions.

- **Início do turno:** 00:10 de Brasília (`10 3 * * *` UTC), com duração máxima de 340 minutos.
- **Complemento:** 05:55 de Brasília (`55 8 * * *` UTC), com duração máxima de 70 minutos.
- A primeira execução desta madrugada foi iniciada manualmente por um push ao workflow às 02:16 de Brasília.
- Máximo 15 consultas Tavily por execução noturna (até 30/dia no total); quando o limite de pesquisas acaba, a coleta ainda pode registrar candidatos públicos do NPPES, mas **não produz e-mails confirmados automaticamente**.
- Execute ou acompanhe em [GitHub Actions → OnCreate Public Healthcare Discovery](https://github.com/lovacademy/oncreate-lead-collector/actions/workflows/collect.yml).

As execuções podem terminar antes se os limites de tempo, crédito, candidatos ou cobertura de fontes forem alcançados. O agendamento do GitHub pode atrasar. O coletor nunca envia e-mails comerciais.


## Revisão de contatos com Claude Haiku (novembro de 2026)

- **FREE_ONLY**: OpenStreetMap + verificação de sites e registros públicos. Não gasta créditos de pesquisa nem tokens de IA.
- **FREE_PLUS**: mantém as fontes gratuitas e, somente com a secret ANTHROPIC_API_KEY disponível, revisa evidências ambíguas de endereços comerciais publicados com claude-haiku-5-5.
- Por padrão, buscas cobradas por Tavily/Brave ficam DESLIGADAS (ALLOW_METERED_SEARCH=false no workflow), mesmo se houver chaves antigas.
- Claude não faz busca no Google/Maps, não encontra endereços inexistentes, não verifica entregabilidade, não substitui verificação documental, não concede consentimento.
- Cada subprocesso pode fazer no máximo duas revisões de contatos por cidade com CLAUDE_MAX_CALLS_PER_CITY=2 e max_tokens=160.
- O coletor desqualifica e-mails cujo domínio não é do site oficial para evitar contatos de contabilidade/agências terceirizadas.
- Limite do OSM: raio de 2,6 km e até 8 sites por cidade para reduzir timeouts urbanos; não corresponde a uma cobertura completa da cidade.

**Ativação da IA:** adicionar ANTHROPIC_API_KEY exclusivamente em GitHub Actions Secrets do repositório público (nunca em código ou frontend), escolher o modo com Claude no CRM e manter CLAUDE_CONTACT_REVIEW=true. Sem essa secret, o custo Anthropic é zero.

Preço de referência em 06/11/2026 (consulte atualizações): Claude Haiku 5.5 a partir de US$ 0,10 por milhão de tokens de entrada e US$ 0,50 por milhão de tokens de saída para prompts até 100 mil tokens. O custo depende dos tokens efetivamente faturados. Fontes oficiais: https://platform.claude.com/docs/en/about-claude/pricing e https://platform.claude.com/docs/en/models/haiku-5-5/overview.

A automação de envio de e-mails é independente; origem pública, revisão e exclusões continuam obrigatórias.


## Pesquisa gratuita por nome da empresa e CNPJ

Para estabelecimentos médicos brasileiros identificados via OSM, o coletor agora tenta resolver o CNPJ em uma fonte de busca pública **Consulta Data Stone** (https://www.datastone.com.br/consulta/api-publica), se o CNPJ não estiver na própria ficha.

- Busca usando o nome comercial conhecido, sem varrer resultados indiscriminadamente.
- Aceita a associação apenas com correspondência consistente de nome, município e UF e situação cadastral ativa.
- Verifica o cadastro pela API OpenCNPJ e aproveita e-mail **somente se o domínio for o mesmo do site oficial do consultório**.
- Registra atribuição à Consulta Data Stone na evidência quando essa fonte for utilizada.
- Se o médico aparecer por um nome e a pessoa jurídica tiver nome completamente diferente, nenhum vínculo é fabricado. O caso deve ser revisado manualmente com fontes adicionais.
- A busca pública gratuita é sujeita a limites/instabilidade da fonte (60 consultas por minuto por IP na documentação consultada).

Nos EUA, EIN não é um método universal de localizar e-mails. O código valida apenas informações específicas de empresas registradas na SEC quando identificadores públicos foram publicados.


## Busca web oficial do Claude (US$ 0,01 por pesquisa)

A integração opcional com Claude Haiku 5.5 também suporta a ferramenta oficial
Anthropic web_search_20250305. É um método de descoberta de sites diferente de
scraping de Google/Google Maps e não exige créditos de Tavily ou Brave.

- **FREE_ONLY:** sem Claude e sem buscas pagas; OpenStreetMap e registros públicos.
- **FREE_PLUS:** no máximo 2 pesquisas de web search por execução
  (US$ 0,02 no máximo pelo serviço de buscas, mais tokens da IA).
- Busca por especialidade + cidade + estado, solicita até 6 sites oficiais e valida
  os links retornados contra os URLs originais da busca oficial.
- Analisa até 4 sites e só cadastra candidatos com e-mail publicado diretamente
  em domínio oficial do estabelecimento. Diretórios, redes sociais, e-mails de
  terceiros e páginas sem comprovação não são importados automaticamente.
- Deduplicação é aplicada no banco pelo domínio; nenhuma pesquisa confere consentimento
  de marketing. Revisão manual precede importação ao CRM.
- Custo estimado e quantidade de pesquisas aparecem no JSON de conclusão do GitHub Actions.
- As fontes públicas OpenStreetMap/Overpass podem ficar sobrecarregadas; a busca Claude
  atua como caminho secundário quando a fonte geográfica falha.

Preço oficial consultado em 07/11/2026: US$ 10/1.000 consultas web
(US$ 0,01 cada) mais tokens do modelo. Fonte:
https://platform.claude.com/docs/en/about-claude/pricing

**Limites técnicos:** CLAUDE_WEB_SEARCH_MAX_PER_RUN=2, max_uses=1 por
solicitação, CLAUDE_RUN_MAX_CALLS=8 para classificação. Buscas Tavily/Brave
permanecem desabilitadas por ALLOW_METERED_SEARCH=false. A chave só reside em
GitHub Actions Secrets.


## Investigação persistente de sites e oportunidades com telefone

A nova arquitetura reaproveita a pesquisa do Claude ao máximo e não amplia,
por padrão, as 2 buscas web cobradas por execução em FREE_PLUS. A busca
retorna os sites oficiais que realmente apareceram no resultado; o Python
cadastra cada domínio novo em `lead_site_research` e investiga até 80
sites por execução, com conclusão/retry registrados no Supabase.

- Site pesquisado: título, descrição, H1, viewport mobile, Open Graph,
  contatos públicos, URLs analisadas e indícios técnicos objetivos.
- No Brasil: CNPJ publicado no próprio site ou encontrado por comparação
  estrita de razão social/cidade/UF; consulta gratuita ao OpenCNPJ; somente
  dados do estabelecimento (razão social, fantasia, CNAEs, endereço comercial,
  data de abertura, situação e telefone).
- Com e-mail comercial publicado e verificado: mantém o pipeline prévio
  `discovered_leads`, sujeito a revisão manual e importação ao CRM.
- Sem e-mail comercial comprovado: encaminha **somente** aqueles com telefone
  comercial verificável, duas ou mais falhas técnicas objetivas e pontuação
  de oportunidade >=65 à tabela `phone_only_leads`, separada do CRM.
- `phone_only_leads` não contém coluna de e-mail, não se conecta ao
  `contacts` nem pode gerar `email_campaign_drafts` ou `email_jobs`.
  É uma fila exclusiva de análise humana para vendedor; não dispara ligações
  ou mensagens.
- Os sites bloqueados por robots/HTTP não são classificados artificialmente
  como "sem e-mail". Nenhuma avaliação de qualidade é visual/definitiva:
  são apenas indicadores documentados que exigem confirmação do vendedor.
- Nunca são extraídos dados de sócios, CPFs ou telefones pessoais do quadro
  societário. E-mails externos à empresa não são importados.
- Cada consulta e investigação tem timeout, retries com backoff e limite
  de duração total de 340 min, conservando 10 min de margem para o job.
- GitHub Actions pode encerrar antes caso a fila ou o orçamento se esgote.
  O próximo job retoma os sites pendentes sem chamar o Claude novamente.

Documentação das fontes públicas:
https://opencnpj.com/api e https://consulta.datastone.com.br/api-publica.
