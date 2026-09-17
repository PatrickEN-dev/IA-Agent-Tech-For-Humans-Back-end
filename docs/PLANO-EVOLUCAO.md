# Plano de evolução: deixar o app pronto para qualquer pessoa testar

Objetivo: fechar os pontos que um entrevistador sênior levantaria e tornar a demo utilizável por um
recrutador sem instruções. Escrito para ser executado por outra sessão (humana ou de agente):
cada item diz o que mudar, onde, como validar e o que já foi verificado no repositório.

Ordem recomendada: Fase 0 inteira, depois item 6 (CI), depois 7 -> 8 -> 9, depois o restante.

Legenda de esforço: P (até meio dia), M (1 a 2 dias), G (3 dias ou mais).

Convenções deste repositório que a execução precisa respeitar:

- Testes rodam com `./venv/Scripts/python.exe -m pytest -q` (Windows) e não chamam LLM
  (`USE_LANGCHAIN=false` no `tests/conftest.py`). Hoje: 213 testes passando.
- Os agentes são singletons criados em `src/api/routes.py` e injetados no `Orchestrator`.
- O front-end fica no repositório irmão `IA-Agent-Tech-For-Humans-Front-end`; valida com
  `npm run lint`, `npx tsc --noEmit` e `npm run build`. Não rodar `npm run build` com o dev server
  aberto no mesmo diretório: o build corrompe o cache do dev server.
- Capturas de tela: há um driver de Playwright em `scratchpad/shots/drive.js` (fora do repo) que usa
  o Chrome instalado (`channel: "chrome"`). Pode ser copiado para `e2e/` no item 14.

---

## Fase 0: os primeiros 60 segundos do recrutador

### 1. Modo demonstração com personas (o problema do CPF) — M

Problema verificado: o app pede um CPF que o visitante não conhece. Quem digita o próprio recebe
"não encontrado" três vezes e a sessão é bloqueada.

Back-end:

1. `src/config.py`: `demo_mode: bool = False`. Ligar com `DEMO_MODE=true` no `render.yaml` e no
   `.env.example`.
2. `src/models/schemas.py`: `DemoPersona {id, nome, cpf, data_nascimento, perfil}` e
   `DemoLoginRequest {session_id, persona_id}`.
3. `src/api/routes.py`:
   - `GET /api/demo/personas`: 404 se `demo_mode` for falso. Devolve 4 personas escolhidas de
     `clientes.csv` (score baixo, médio, alto e um perfil com limite alto). O texto `perfil` é
     montado no código a partir do score e da tabela `score_limite.csv`, não fica hard-coded.
   - `POST /api/unified/demo-login`: 404 se `demo_mode` for falso. Executa no `Orchestrator` o
     mesmo caminho da autenticação por chat (CPF e data da persona) e devolve o mesmo
     `UnifiedChatResponse` que o chat devolveria. Isso evita o front mandar duas mensagens em
     sequência e evita mostrar o CPF como mensagem do usuário.
   - No `Orchestrator`, extrair de `_handle_cpf_collection` e `_handle_birthdate_collection` um
     método `authenticate_session(session_id, cpf, birthdate)` reutilizado pelos dois caminhos.
4. Mensagem de boas-vindas (`init_session`) ganha uma frase quando `demo_mode` está ligado:
   "Este é um ambiente de demonstração com dados fictícios. Não use seu CPF real."

Front-end:

5. `src/services/api.service.ts`: `getPersonas()` e `demoLogin(personaId)`.
6. `src/hooks/useChat.ts`: carregar personas após o `init` (ignorar 404 silenciosamente) e expor
   `personas` e `loginAsPersona`.
7. `SessionPanel.tsx`: seção "Clientes de demonstração" com um botão por persona
   ("Maria Helena · score 315 · limite R$ 1.000"), visível só antes da identificação.
8. `QuickReplies.tsx`: no estado `collecting_cpf`, chips "Entrar como Maria" etc. (mobile não vê o
   painel lateral).
9. Aviso fixo abaixo do campo de mensagem enquanto `demo_mode`: "Dados fictícios. Não use seu
   CPF real."

Testes: `tests/test_demo.py` cobrindo 404 sem demo mode, lista de personas, login por persona
devolvendo `authenticated: true` e `state: authenticated`. Um teste no front (item 14) clica na
persona e espera o menu.

Pronto quando: um visitante sem ler nada autentica em dois cliques, no desktop e no celular.

### 2. Validação de CPF com dígitos verificadores e máscaras — M

Fato verificado (script rodado sobre `src/data/clientes.csv`): 19 dos 20 CPFs da base são
inválidos pelo algoritmo de dígitos verificadores. Só `52998224725` (Maria Helena) é válido. Nos
testes, `12345678901` é inválido e aparece 46 vezes em 9 arquivos; `98765432100` é válido.

Ordem obrigatória (senão a suíte quebra no meio):

1. `src/utils/cpf.py`: `is_valid_cpf(cpf) -> bool` (rejeita tamanho diferente de 11 e dígitos
   todos iguais) e `generate_valid_cpf(seed)` para o passo 2. Testes unitários com os cinco casos
   já conferidos: `12345678901` falso, `98765432100` verdadeiro, `12345678909` verdadeiro,
   `11122233344` falso, `99999999999` falso.
2. `scripts/fix_client_cpfs.py`: reescreve `clientes.csv` trocando cada CPF inválido por um válido
   gerado de forma determinística (mesma seed = mesmo resultado), mantendo Maria. Atualizar as
   tabelas de CPFs em `README.md`, `README-RECRUTADOR.md` e `docs/DOCUMENTACAO-TECNICA.md`
   (3 ocorrências lá). O item 1 lê as personas do CSV, então o front não precisa de mudança.
3. Nos testes, trocar `12345678901` por `12345678909` em todos os arquivos (`sed` ou
   substituição global), inclusive no CSV embutido em `tests/conftest.py`. Rodar a suíte: deve
   continuar em 213 passando antes de ligar a validação.
4. Só então ligar a validação em `_handle_cpf_collection` (chat) e em `TriageAgent.authenticate`
   (endpoint): CPF sintaticamente inválido responde "Esse número não é um CPF válido. Confira os
   dígitos." e não consulta a base. Continua contando tentativa (evita força bruta barata).
   O teste `test_lockout_after_three_failed_attempts` usa `99999999999`: passa a bater na
   mensagem de inválido, e só o estado final é verificado, então continua passando.
5. Front: máscara `000.000.000-00` no estado `collecting_cpf` e `DD/MM/AAAA` em
   `collecting_birthdate`, aplicada no `onChange` do campo (sem biblioteca; 15 linhas em
   `ChatInput.tsx`). O texto enviado ao back-end pode ir com a máscara: `extract_cpf_from_text`
   já remove pontuação.

Pronto quando: `scripts/fix_client_cpfs.py` roda sem alterar nada (idempotente), há um teste
`test_all_client_cpfs_are_valid` lendo o CSV de produção, e a suíte está verde.

### 3. Bloqueio com saída — P

1. `Orchestrator._locked_response`: quando `demo_mode`, a mensagem inclui "Você pode continuar
   com um cliente de demonstração" e o front mostra as personas mesmo no estado `goodbye`.
2. Contar tentativas por CPF também no chat: reaproveitar o `_AttemptRecord` do `TriageAgent`
   em um `AuthAttemptTracker` (novo módulo `src/services/auth_attempts.py`) usado pelos dois.
   Em `tests/conftest.py`, adicionar uma fixture `autouse` que chama `tracker.reset()` a cada
   teste, porque todos os testes autenticam com o mesmo CPF.

Pronto quando: três erros de data com o mesmo CPF em sessões diferentes bloqueiam aquele CPF
por `AUTH_LOCKOUT_MINUTES`, e a suíte segue verde.

### 4. Cold start do Render — P

Fatos verificados na documentação do Render (2026): serviços web gratuitos dormem após 15
minutos sem tráfego e levam cerca de um minuto para acordar; o workspace tem 750 horas de
instância gratuitas por mês. Um serviço sempre ativo consome no máximo 744 horas em um mês de
31 dias, então cabe, desde que seja o único serviço gratuito do workspace.

1. Criar um monitor em cron-job.org ou UptimeRobot chamando `GET /health` a cada 10 minutos.
   Isso é configuração externa, não código; registrar no README a URL monitorada.
2. Manter o aviso "o assistente está iniciando" no front como rede de segurança.
3. Se o workspace tiver outro serviço gratuito, o ping precisa ser restrito a um horário (por
   exemplo 8h às 22h) para não estourar as 750 horas.

### 5. README como landing page — P

1. Capturas de desktop e celular geradas com o driver de Playwright (já produz PNG). Salvar em
   `docs/screenshots/` no repositório do front e referenciar nos dois READMEs.
2. GIF é opcional: exige `ffmpeg` para converter o vídeo do Playwright, e não há garantia de que
   está instalado. Se não estiver, usar só as capturas.
3. Seção "Teste em um minuto": abrir a demo, clicar em uma persona, três frases para tentar.
4. Diagrama da arquitetura híbrida (pode ser Mermaid, que o GitHub renderiza).

---

## Fase 1: o que um sênior pergunta na entrevista

### 6. CI antes de refatorar — P

Back-end, `.github/workflows/ci.yml`: Python 3.11 e 3.12, `pip install -r requirements-dev.txt`,
`ruff check .` (adicionar `ruff` ao `requirements-dev.txt` e um `[tool.ruff]` mínimo no
`pyproject.toml`), `pytest --cov=src --cov-fail-under=80`. A cobertura atual precisa ser medida
antes de fixar o número; se estiver abaixo de 80, usar o valor medido menos 2 pontos.

Front-end, `.github/workflows/ci.yml`: Node 20, `npm ci`, `npm run lint`, `npx tsc --noEmit`,
`npm run build`. O job de Playwright (item 14) entra depois, com a API mockada, para não depender
do outro repositório.

Badges de status nos dois READMEs. Entra antes de qualquer refatoração grande.

### 7. Persistência de verdade — G

Fato verificado: o Render gratuito não oferece disco persistente; qualquer arquivo gravado (CSV
ou SQLite) volta ao estado do deploy no próximo deploy ou reinício. O Postgres gratuito do Render
expira 30 dias após a criação (mais 14 de carência). Para uma demo, portanto:

1. SQLAlchemy 2 (async, `aiosqlite` local, `asyncpg` em produção) com `DATABASE_URL`
   (padrão `sqlite+aiosqlite:///./data/banco_agil.db`).
2. Modelos `Client`, `ScoreLimit`, `LimitRequest` em `src/db/models.py`; repositórios em
   `src/db/repositories.py` com a mesma interface que `CSVService` expõe hoje
   (`get_client_by_cpf`, `update_client_score`, `append_limit_request`, `read_score_limits`),
   para trocar a injeção em `routes.py` sem tocar nos agentes.
3. `scripts/seed.py` importa os três CSVs. Flag `DEMO_RESET_ON_START=true` roda o seed no
   `lifespan`, o que é desejável na demo (dados sempre limpos).
4. Alembic para migrações, com a migração inicial gerada.
5. `tests/conftest.py`: substituir o diretório temporário de CSV por um SQLite temporário com
   seed; a fixture `_reset_test_data` passa a recriar o banco. O `conftest` é reescrito por
   inteiro.
6. Documentar os dois caminhos: SQLite com reset para demo; Postgres (Neon, Supabase ou Render
   pago) para produção.

### 8. Sessões fora do processo — M

1. `src/services/session_store.py`: `SessionStore` (protocolo) com `InMemorySessionStore`
   (padrão, com o TTL atual) e `RedisSessionStore` (opcional, `REDIS_URL`; serializar
   `OrchestratorSession` com `dataclasses.asdict`/JSON). O Render tem "Key Value" gratuito com
   25 MB, suficiente.
2. `GET /api/unified/session/{id}`: devolve estado, `authenticated`, `user_name`,
   `available_actions` e as últimas mensagens (`conversation_history`, hoje limitado a 20).
   404 se a sessão não existir.
3. Front: ao carregar a página, se houver `chat_session_id` no `sessionStorage`, chamar o `GET`
   antes do `init`; em 404, seguir para o `init` normal. Com isso, recarregar a página não perde
   a conversa.

### 9. Regras de negócio honestas — M

Fatos verificados: `evaluate_limit_request` nunca produz `pending_analysis`; um pedido
"aprovado" não altera nada; `available_limit` é `current_limit * 0.8` fixo e é verificado em
`tests/test_credito.py:16` e `tests/test_complete_flows.py:59`; a coluna `limite_atual` do CSV
não é usada para calcular nada; na base de produção Maria tem `limite_atual` 15000 com score
315, que pela tabela dá 1000.

Decisões propostas (confirmar antes de codar):

1. Limite atual = `limite_atual` persistido por cliente. Teto = tabela por score.
2. Pedido até o teto: aprovado e `limite_atual` passa a ser o valor pedido. Entre o teto e 1,5x
   o teto com score >= 600: `pending_analysis` (registrado, sem alterar o limite). Acima disso:
   negado com oferta de entrevista.
3. Remover `available_limit` da resposta e da mensagem ("Disponível") em vez de inventar um
   número. Atualizar os dois testes citados.
4. Entrevista: `novo = round(0.6 * atual + 0.4 * calculado)` e a mensagem lista os dois fatores
   de maior peso ("renda/despesas contribuiu +X", "dívidas pesaram -Y").
5. Corrigir o seed para `limite_atual` coerente com a tabela (item 7 já reseeda).

Testes a reescrever no mesmo commit: `test_value_below_current_limit_is_explained`,
`test_value_in_intent_message_is_used`, `test_unified_credit_increase_with_value`,
`test_unified_credit_denied_offers_interview`, os dois de `available_limit` e os que verificam
"aprovado" em `tests/test_credito.py`.

### 10. Segurança e abuso — M

1. Rate limit com `slowapi` em `/unified/chat` (por exemplo 60/min por IP) e
   `/triage/authenticate` (10/min). Setting `rate_limit_enabled: bool = True`, desligado no
   `conftest`, senão a suíte inteira leva 429.
2. Cabeçalhos de segurança no `next.config.mjs` (`headers()`): `X-Frame-Options`,
   `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`. CSP só se for testada com
   `next/font`, que injeta estilos inline.
3. Prompt injection na humanização: a humanização recebe o texto do usuário. O guarda é
   determinístico: `LLMService._preserves_facts(technical, humanized)` extrai números, valores em
   R$, códigos de moeda e datas da resposta técnica e exige que todos apareçam na humanizada;
   caso contrário usa o template. Testável sem LLM: injetar um `LLMService` falso que devolve
   "seu limite é R$ 1.000.000,00" e verificar que a resposta final mantém o valor técnico.
4. Documentar em `docs/DOCUMENTACAO-TECNICA.md` que CPF + data de nascimento não é autenticação
   forte: é restrição do desafio, mitigada por bloqueio por CPF, rate limit e dados fictícios.

### 11. Observabilidade — M

1. Middleware de request id (`X-Request-ID`, gerado se ausente) e `contextvars` para incluí-lo
   em todos os logs.
2. Formatter JSON em `src/utils/logging_config.py` (sem dependência nova: `json.dumps` no
   `format`).
3. No `Orchestrator.process_message`, medir tempo total e registrar se o turno usou LLM
   (`llm_used: true/false`, `llm_ms`). Contador em memória exposto em `/health` como
   `turns_total` e `llm_turns_total`. É esse número que vira a linha do CV ("menos de X% dos
   turnos chamam o modelo"). Medir antes de escrever a porcentagem.

---

## Fase 2: o que diferencia de "usei LLM"

### 12. Avaliação de intenção — M

1. `evals/intents.jsonl`: 100 frases com intenção esperada, escritas à mão, cobrindo os 10
   rótulos de `IntentType` e variações informais.
2. `scripts/eval_intents.py`: acurácia de `classify_with_rules`, do LLM (se chave presente) e do
   híbrido; imprime matriz de confusão. Roda no CI só no modo regras.
3. Saída estruturada no classificador: `llm.with_structured_output(IntentResult)` do LangChain,
   com `IntentResult(intent: Literal[...], confidence: float)`. Funciona com OpenAI e Anthropic.

### 13. Entrevista conversacional — G

1. Extrator determinístico por rótulo em `src/utils/value_extractor.py`: renda liga-se a
   "ganho/renda/recebo/salário", despesas a "gasto/despesa/pago/contas", dependentes a
   "filhos/dependentes", dívidas a `parse_boolean_response` no trecho com "dívida". Dois
   valores monetários sem rótulo continuam ambíguos e caem no fluxo pergunta a pergunta.
2. Em `_start_interview`, tentar o extrator na mensagem de abertura; preencher o que for
   inequívoco e perguntar só o que faltou; antes de gravar, mostrar um resumo e pedir confirmação
   (reutiliza `pending_redirect`/confirm).
3. LLM opcional como segundo extrator, sempre validado pelas mesmas regras.

### 14. Testes de front — M

1. Vitest + Testing Library (`npm i -D vitest @testing-library/react jsdom`): testes de
   `parseBlocks`, `getQuickReplies`, `describeApiError`.
2. Playwright em `e2e/chat.spec.ts` com a API mockada via `page.route("**/api/**")` e fixtures
   de resposta; assim o CI do front não depende do repositório do back-end. Um segundo teste
   "live", fora do CI, aponta para a API real e usa a persona do item 1.
3. No CI: `npx playwright install --with-deps chromium` antes de rodar.

### 15. Higiene — P

- Apagar `src/agents/orchestrator_v2.py` (rascunho não adotado; documentado em
  `docs/arquitetura-hibrida-v2.md`).
- Mover `tests/test_integration.py` para `scripts/smoke_integration.py`: verificado que o pytest
  não coleta nenhuma função dele (as funções `test_*` são internas a `run_integration_tests`).
- `pre-commit` com ruff e prettier; Dependabot para pip e npm; `.env.example` com
  `DEMO_MODE`, `DEMO_RESET_ON_START`, `DATABASE_URL`, `REDIS_URL`, `RATE_LIMIT_ENABLED`,
  `AUTH_LOCKOUT_MINUTES`, `MAX_MESSAGE_LENGTH`.

---

## Revisões do plano

### Revisão 1: bugs e conflitos

- Validar dígitos verificadores antes de trocar as fixtures quebra 46 usos de `12345678901` em 9
  arquivos de teste. A ordem do item 2 é obrigatória.
- Bloqueio por CPF no chat quebra a suíte, porque todos os testes autenticam com o mesmo CPF.
  A fixture `autouse` de `reset()` no item 3 resolve.
- Retomar sessão no reload exige tentar o `GET` antes do `init` e tratar 404. Sem isso, dois inits
  em sequência.
- Migrar para banco muda o isolamento dos testes (hoje diretório temporário de CSV). O `conftest`
  é reescrito por inteiro no item 7.
- Rate limit precisa ser desligável por configuração, ou a suíte inteira leva 429.
- Mudar as regras de crédito invalida os testes listados no item 9. Reescrever junto com a regra.

### Revisão 2: ordem e dependências

- CI (6) logo depois da Fase 0, antes de qualquer refatoração grande.
- Banco (7) antes de sessões (8) e regras (9), senão o código de regras é escrito duas vezes.
- Personas no front e endpoint saem no mesmo commit; o e2e "live" (14) depende deles.
- Remover `available_limit` toca o schema e dois testes (já localizados).
- SQLite no Render zera a cada deploy: aceitável e desejável na demo com reset; para produção,
  Postgres. Documentar os dois caminhos.

### Revisão 3: verificação contra o repositório e fontes externas

Correções feitas nesta revisão em relação à versão anterior do plano:

- "Vários CPFs inválidos" era impreciso: são 19 de 20 na base de produção (script rodado). O
  item 2 ganhou um script de correção determinístico e um teste sobre o CSV real.
- "Cerca de 40 testes" era estimativa: são 46 ocorrências em 9 arquivos, mais 3 na documentação
  técnica. `12345678909` foi conferido como substituto válido.
- "Clicar envia CPF e data em sequência" foi trocado por um endpoint `demo-login`: mandar duas
  mensagens encadeadas pelo front é frágil e exibiria o CPF como mensagem do usuário.
- Render: 750 horas de instância por mês por workspace e sono após 15 minutos foram confirmados
  na documentação de 2026; Postgres gratuito expira em 30 dias (não 90). O item 7 passou a
  recomendar SQLite com reset para a demo e Postgres externo para produção.
- Teste de prompt injection sem LLM era impossível como estava escrito; passou a ser um guarda
  determinístico (`_preserves_facts`) testado com um `LLMService` falso.
- E2E no CI do front dependia de clonar o outro repositório; passou a usar API mockada, com o
  teste "live" fora do CI.
- GIF no README depende de `ffmpeg`, que pode não existir; marcado como opcional.
- `available_limit` está em dois testes (localizados), não "em alguns".
- Meta de cobertura de 80% no CI só depois de medir a atual.

Fontes consultadas para os fatos externos:

- Render, "Deploy for Free": https://render.com/docs/free
- "Is Render Free? Free Tier Limits, Sleep, and the 30-Day DB (2026)":
  https://justinmckelvey.com/blog/is-render-free
- "Render Free Tier 2026: 750 Hours, Redis, Cron Jobs":
  https://unanswered.io/guide/render-free-tier-details
