# Prompt: Evolução do Banco Ágil — de MVP para produção robusta

> **Para quem usa este arquivo:** este é um briefing técnico completo,
> escrito para ser entregue a um agente de IA codificador (Claude Code,
> Codex, Cursor) que vai implementar as melhorias. Leia tudo antes de
> escrever qualquer linha de código. Quando for executar, siga a ordem
> das **fases**, faça um PR por fase, valide com os testes e só então
> siga para a próxima.

---

## 0. Contexto atual (estado deste repositório)

- API FastAPI em Python 3.11+, autenticação JWT, 4 agentes bancários
  conversacionais (`triage`, `credit`, `interview`, `exchange`)
  coordenados por um `Orchestrator` fino.
- Persistência em CSV (3 arquivos em `src/data/`).
- LLM opcional via LangChain (`OPENAI_API_KEY` ou `ANTHROPIC_API_KEY`).
- Sessões in-memory com TTL de 30min.
- Testes em `pytest`, ~120 verdes.

A arquitetura está bem desenhada (Strategy + DDD-light). O objetivo
**não** é reescrever — é elevar cada camada ao patamar de produção sem
inflar complexidade.

---

## 0.1 Quick wins — "se eu só tenho 1 dia"

Se o tempo for muito curto e o objetivo for **maximizar impacto por
hora**, faça apenas estes itens (são todos da Fase 1 + parte da Fase 4):

1. CI no GitHub Actions (lint + tests + coverage).
2. `asyncio.to_thread` nos métodos do `ClientRepository`.
3. Cache de `read_score_limits` na `ScoringService` (TTL 60s).
4. Headers de segurança (HSTS, X-Content-Type-Options, X-Frame-Options,
   Referrer-Policy) — middleware FastAPI em ~20 linhas.
5. Rate limit no `/api/triage/authenticate` (5/min por IP) — pode ser
   slowapi ou middleware simples sem Redis.
6. Sentry capturando exceções não tratadas.

Esses 6 itens resolvem ~70% do risco operacional do app atual sem
exigir nenhuma migração de dados.

---

## 1. Resultado esperado

Ao concluir todas as fases, o projeto deve ter:

| Capacidade            | MVP atual                | Alvo                                                  |
| --------------------- | ------------------------ | ----------------------------------------------------- |
| Persistência          | CSV + filelock           | PostgreSQL + Alembic + pool async                     |
| Sessões               | dict em memória          | Redis com TTL + cluster-safe                          |
| Auth                  | JWT 15min                | JWT + refresh tokens + revocation list                |
| Observabilidade       | logs texto               | logs JSON + OpenTelemetry + Prometheus + Sentry       |
| Rate limiting         | só `max_auth_attempts`   | slowapi por IP + Redis token bucket por CPF/sessão    |
| Headers de segurança  | só CORS                  | CSP, HSTS, X-Frame-Options, Referrer-Policy           |
| LGPD                  | logs ofuscam CPF         | criptografia at-rest, direito ao esquecimento, audit  |
| CI/CD                 | manual                   | GitHub Actions: lint + type + tests + cobertura ≥ 90% |
| Container             | Dockerfile simples       | multi-stage + non-root + healthcheck + Helm chart     |
| Frontend              | Streamlit antigo         | Next.js 14 + Tailwind + streaming SSE                 |
| Testes                | unit + integração HTTP   | + load test (Locust) + contract test (Schemathesis)   |

---

## 2. Princípios não-negociáveis

1. **Compatibilidade reversa**: nenhum endpoint público pode mudar de
   contrato sem versionamento (`/api/v1/...`). Já existe — manter.
2. **Sem regressão de UX conversacional**: o agente nunca pode voltar a
   recusar pedidos ambíguos. Toda mudança que passe perto da camada LLM
   precisa ter um teste de "off-topic não trava".
3. **Sem overengineering**: adicione abstração SÓ quando o segundo caso
   de uso aparecer. CQRS, ports/adapters, event sourcing, mediator —
   **não**. DDD-light continua suficiente.
4. **Testes acompanham o código**: toda fase entrega testes verdes. Se
   uma fase quebra testes existentes, ou (a) os testes estão errados e
   precisam ser corrigidos no MESMO PR explicando o motivo, ou (b) a
   mudança está errada.
5. **Migração de dados é parte do trabalho**: ao trocar CSV por banco,
   entregar script `scripts/migrate_csv_to_postgres.py` idempotente.

---

## 3. Fases (cada uma é um PR independente)

### Fase 1 — Saneamento técnico (1-2 dias)

**Objetivo**: deixar a base pronta para receber as próximas fases.

- [ ] Adicionar `ruff` + `mypy --strict` + `pre-commit` hooks.
- [ ] Adicionar `.github/workflows/ci.yml`: lint, type-check, pytest,
      cobertura ≥ 90% (`coverage`), bloqueia merge se cair.
- [ ] Substituir os I/O síncronos do `ClientRepository` por
      `asyncio.to_thread(...)` (CSV ainda fica, mas não bloqueia o
      event loop).
- [ ] Cache de `read_score_limits()` em `ScoringService` (TTL 60s).
- [ ] Cache da instância do LLM em `LLMGateway._llm` (hoje recria
      cliente por chamada).
- [ ] Trocar `httpx.AsyncClient` por instância única reutilizada em
      `ExchangeRateAPI` (connection pooling).
- [ ] Adicionar `pyproject.toml` config para `pytest --cov-fail-under=85`.

**Critério de pronto**: CI verde + `pytest --cov` mostra ≥ 85%.

---

### Fase 2 — PostgreSQL + Alembic (2-3 dias)

**Objetivo**: trocar CSV por banco, mantendo a interface de
`ClientRepository`.

- [ ] Adicionar `sqlalchemy[asyncio]>=2.0`, `asyncpg`, `alembic`.
- [ ] Criar `src/infra/db.py` com `AsyncEngine`, `async_sessionmaker`,
      injeção via `Depends`.
- [ ] Modelos ORM em `src/infra/models/`:
  - `ClientModel` (cpf PK, nome, data_nascimento, score, limite_atual,
    created_at, updated_at).
  - `ScoreLimitModel` (score_min, score_max, limit).
  - `LimitRequestModel` (id PK, cpf FK, data_hora, limites, status).
  - `AuditLogModel` (id, user_id, event, payload jsonb, created_at).
- [ ] Implementar `SqlClientRepository` que respeita a mesma assinatura
      de `ClientRepository`. Manter a versão CSV como fallback para
      `data_dir=` em testes locais.
- [ ] Criar Alembic com primeiro migration; seed inicial a partir do
      CSV atual.
- [ ] `scripts/migrate_csv_to_postgres.py` idempotente (UPSERT por CPF).
- [ ] Variáveis novas no `.env.example`:
      `DATABASE_URL=postgresql+asyncpg://...`.
- [ ] Atualizar `docker-compose.yml` com serviço `postgres:16` +
      healthcheck.

**Critério de pronto**: todos os testes passam contra Postgres em CI
(usando `testcontainers-postgres` ou serviço do Actions).

---

### Fase 3 — Sessões em Redis (1 dia)

**Objetivo**: tirar `SessionStore` da memória para o app rodar com
múltiplos workers.

- [ ] Adicionar `redis>=5.0` (cliente async).
- [ ] Criar `RedisSessionStore` que implementa a mesma interface
      (`create`, `get_or_create`, `clear`).
- [ ] Serializar `Session` como JSON (campos já são string/dict/list).
      `pending_redirect` e `history` cabem direto.
- [ ] Key prefix: `bancoagil:session:{uuid}` com TTL nativo do Redis
      configurável via `SESSION_TTL_SECONDS`.
- [ ] Fallback automático para `InMemorySessionStore` quando
      `REDIS_URL` não está setada (mantém DX local intacto).
- [ ] Atualizar `docker-compose.yml` com `redis:7`.
- [ ] Teste de integração que sobe Redis real e valida persistência
      cross-process.

**Critério de pronto**: rodar `gunicorn -w 4 src.main:app` com Redis e
ver conversação manter contexto entre workers.

---

### Fase 4 — Rate limiting + headers de segurança (1 dia)

- [ ] Adicionar `slowapi` (ou implementar middleware próprio com Redis
      token bucket — preferir o próprio, sem dependência nova grande).
- [ ] Limites:
  - `/api/triage/authenticate`: 5 req/min por IP, 3 req/min por CPF
    (chave: ip + cpf nos primeiros 3 dígitos).
  - `/api/chat`: 30 req/min por sessão.
  - `/api/exchange`: 60 req/min por usuário autenticado.
- [ ] Adicionar `SecurityHeadersMiddleware` enviando:
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Content-Security-Policy: default-src 'self'` (ajustar por endpoint
    se servir frontend).
- [ ] Corrigir CORS: se `allow_origins=["*"]`, forçar
      `allow_credentials=False` (a spec proíbe combinação).
- [ ] Adicionar teste: 6ª chamada em 1min para `/triage/authenticate`
      vinda do mesmo IP recebe `429`.

**Critério de pronto**: scan com `nikto` ou `zap-baseline` não acusa
issues high/critical relacionados a headers.

---

### Fase 5 — Auth com refresh tokens + revocation (1-2 dias)

- [ ] Criar `RefreshTokenModel` (token_hash, cpf, expires_at, revoked).
- [ ] Endpoints novos:
  - `POST /api/auth/refresh` → troca refresh por access novo.
  - `POST /api/auth/logout` → revoga refresh.
- [ ] Access token continua 15min; refresh dura 30 dias.
- [ ] Revocation list no Redis (`bancoagil:revoked:{jti}`) com TTL =
      `exp - now`.
- [ ] `AuthService.verify_token` agora chama Redis para checar `jti`.
- [ ] Adicionar `jti` ao payload do JWT.
- [ ] Doc no README sobre o fluxo.

---

### Fase 6 — Observabilidade (2 dias)

- [ ] **Logs estruturados**: trocar `logging` por `structlog` com
      formatter JSON, ID de request via `contextvars`.
- [ ] **OpenTelemetry**: instrumentar FastAPI, httpx, asyncpg, redis.
      Exportar OTLP para o coletor (configurável).
- [ ] **Prometheus**: expor `/metrics` com latência por endpoint,
      contagem de intents, taxa de fallback do LLM, cache hit rate.
- [ ] **Sentry**: capturar exceções não tratadas; integrar
      `before_send` para remover CPF do payload.
- [ ] Dashboards Grafana versionados em `infra/grafana/`.
- [ ] Alertas (Prometheus rules):
  - p95 `/api/chat` > 2s por 5min → warning.
  - Taxa de `denied` em `/credit/request_increase` > 80% / 1h → info.
  - Erros 5xx > 1% por 5min → critical.

---

### Fase 7 — Eval framework do LLM (1-2 dias)

**Objetivo**: garantir que mudanças no prompt do agente **não regridem**
o comportamento esperado.

- [ ] Criar `evals/scenarios/*.yaml`. Cada arquivo:
  ```yaml
  name: off_topic_redirects_to_menu
  setup:
    auth: true
  conversation:
    - user: "qual a capital do brasil?"
    - assistant_must_contain_any: ["limite", "moedas", "perfil"]
    - assistant_must_not_contain: ["não posso ajudar", "não posso te ajudar"]
  ```
- [ ] Runner em `evals/run.py` que executa cenários contra o
      `Orchestrator` real (com LLM ligado) e produz relatório
      `evals/report.html`.
- [ ] CI roda evals em `main` (não bloqueia PR — caro), publica
      tendência ao longo do tempo.
- [ ] Cenários mínimos:
  - Pergunta fora de contexto não recusa.
  - Cancel sai do fluxo.
  - Help repete pergunta atual.
  - Mensagem confusa → clarificação.
  - Saudação no meio do fluxo retoma pergunta.
  - Mudança de assunto pede confirmação.

---

### Fase 8 — Fallback entre provedores LLM (1 dia)

- [ ] Em `LLMGateway`, lista de provedores ordenada (`openai`,
      `anthropic`, `local`).
- [ ] Tentar cada um com timeout próprio; se todos falharem, usar o
      `_fallback_humanize` atual.
- [ ] Circuit breaker simples: se um provedor falha 3x em 30s, pula
      pelos próximos 60s.
- [ ] Métrica Prometheus `llm_provider_failures_total{provider=...}`.

---

### Fase 9 — Frontend Next.js (3-5 dias)

> Aposentar o Streamlit antigo. Frontend novo em repositório separado
> ou subpasta `frontend/`.

- [ ] Next.js 14 + App Router + TypeScript + Tailwind + shadcn/ui.
- [ ] Componentes:
  - `<ChatWindow>` com streaming SSE.
  - `<MessageBubble>` com markdown limitado.
  - `<QuickActions>` chips dos 4 serviços.
  - `<AuthForm>` para login direto via REST.
- [ ] Página `/chat` consome `/api/v1/chat` (renomear endpoint para
      `/api/v1/...`) com auto-init de sessão.
- [ ] Página `/limite` mostra `/api/v1/credit/limit` (com SSR).
- [ ] Dark mode.
- [ ] E2E com Playwright: fluxo completo de auth → consulta → aumento
      → entrevista.

---

### Fase 10 — Container hardening + Helm (1 dia)

- [ ] `Dockerfile` multi-stage: builder + runtime alpine/distroless,
      `USER 65532:65532`, healthcheck.
- [ ] `infra/helm/bancoagil/` com `Chart.yaml`, `values.yaml`,
      templates de `Deployment`, `Service`, `Ingress`, `HPA`,
      `NetworkPolicy`.
- [ ] Secrets via `ExternalSecrets` (Vault / AWS Secrets Manager).
- [ ] Liveness `/health`, readiness `/health/ready` (que checa Redis +
      DB).

---

### Fase 11 — LGPD/compliance (1-2 dias)

- [ ] Endpoint `POST /api/v1/me/forget` (autenticado): apaga ou anonimiza
      dados pessoais do CPF (soft-delete; mantém audit log com hash).
- [ ] Endpoint `GET /api/v1/me/data`: portabilidade (export JSON).
- [ ] Coluna `clients.cpf` criptografada com `pgcrypto` (chave em
      Vault) — busca via hash determinístico.
- [ ] Audit log de toda operação que toca CPF (read, update,
      anonimização).
- [ ] DPA e política de retenção documentadas em `docs/lgpd.md`.

---

## 4. Pontos de atenção específicos

### 4.1 Não regredir o "nunca recusa"

Existe risco real de qualquer mudança no LLM ou no roteador reintroduzir
o comportamento de "não posso ajudar". Antes de mergear qualquer PR que
toque `services/llm.py`, `core/intents.py` ou `core/orchestrator.py`,
rode os evals (fase 7). Se ainda não houver evals, manter o teste
`test_off_topic_never_refuses` verde já dá uma proteção mínima.

### 4.2 Migração CSV → Postgres sem downtime

- Dual-write durante a transição: cada `update_score` escreve nos dois
  lugares; reads vêm do Postgres com fallback para CSV se vazio.
- Switch via feature flag `DB_BACKEND=postgres|csv` no `.env`.
- Após uma semana estável em prod, remover código CSV.

### 4.3 Token bucket no Redis sem corrida

Usar `INCR` + `EXPIRE` (com `EXPIRE NX` no Redis 7+) ou o script Lua
abaixo:

```lua
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
```

### 4.4 Sessões com PII

`Session.history` guarda mensagens do usuário (pode conter CPF, valores,
dados). Ao mover para Redis:
- TTL agressivo (manter 30min default).
- Criptografar valor antes de gravar (Fernet com chave do Vault) — ou
  pelo menos pseudonimizar CPF.
- Nunca logar `Session` inteira; usar `__repr__` que redacta.

### 4.5 LLM prompt — versionamento

Criar `src/services/llm_prompts/v1.txt` e `v2.txt`. `LLMGateway` lê o
arquivo apontado por `LLM_PROMPT_VERSION` no settings. Permite A/B test
e rollback rápido.

---

## 5. Como mensurar sucesso

Métricas mínimas para considerar a evolução "concluída":

| Métrica                                       | Hoje | Alvo |
| --------------------------------------------- | ---- | ---- |
| Cobertura de testes                           | ~85% | ≥ 90% |
| p95 `/api/chat` (LLM off)                     | ~50ms | ≤ 100ms |
| p95 `/api/chat` (LLM on)                      | ~1.5s | ≤ 2s   |
| Taxa de erro 5xx                              | n/d  | < 0.1% |
| Mean time to recovery (MTTR)                  | n/d  | < 30min |
| % conversas que terminam com handoff humano   | n/d  | < 5%    |
| % conversas em que agente diz "não posso"     | n/d  | 0%      |

---

## 6. Checklist final

Antes de declarar v1.0:

- [ ] Todas as fases acima fechadas.
- [ ] `pytest --cov-fail-under=90` verde.
- [ ] `mypy --strict src/` zero erros.
- [ ] `ruff check .` zero issues.
- [ ] `docker-compose up` sobe app + postgres + redis funcionais.
- [ ] Smoke test E2E (Playwright) verde.
- [ ] OWASP ZAP baseline scan sem high/critical.
- [ ] Documentação atualizada: README, CLAUDE.md, docs/runbook.md,
      docs/architecture.md, docs/lgpd.md.
- [ ] Plano de rollback documentado para cada fase.
