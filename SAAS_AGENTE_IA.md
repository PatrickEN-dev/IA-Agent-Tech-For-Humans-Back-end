# Prompt: SaaS de agentes de IA — do zero ao GA

> **Para quem usa este arquivo:** este é um briefing de produto e
> arquitetura **completo**, escrito para ser entregue a um agente de IA
> codificador (Claude Code, Codex, Cursor) que vai construir o SaaS do
> zero. Leia tudo antes de começar. As seções estão ordenadas para
> serem lidas em sequência: visão → modelo de dados → arquitetura →
> implementação → operação.

---

## 1. Visão de produto

### 1.1 Em uma frase

> Uma plataforma multi-tenant onde qualquer empresa configura um time
> de **agentes de IA especializados** que conversam com seus usuários,
> trocam de papel entre si quando o assunto muda, e usam **ferramentas**
> para executar ações no backend do cliente — tudo via no-code/low-code,
> com SDK e widget embedável.

### 1.2 Inspiração arquitetural

Este projeto nasceu da observação de que o padrão usado no "Banco Ágil"
(4 agentes — triagem, crédito, entrevista, câmbio — com um orquestrador
fino que troca o agente ativo conforme a intenção do usuário) é
**genérico**. Funciona para: e-commerce (suporte, vendas, devolução,
status do pedido), saúde (triagem, agendamento, exames, financeiro),
educação (matrícula, financeiro, suporte ao aluno, biblioteca),
imobiliária, cobrança, jurídico, etc.

O SaaS empacota essa receita e deixa o cliente final só configurar
**quais agentes existem, o que cada um faz e quais ferramentas tem**.

### 1.3 Personas

| Persona       | Papel                                  | Frente que usa             |
| ------------- | -------------------------------------- | -------------------------- |
| **Builder**   | Configura agentes (no-code)            | Painel web (Builder UI)    |
| **Developer** | Integra via API/SDK/webhook            | Documentação + API console |
| **End-user**  | Conversa pelo widget ou canal externo  | Widget / WhatsApp / e-mail |
| **Admin**     | Audita, vê analytics, gerencia billing | Painel admin               |

### 1.4 Diferenciais
1. **Multi-agente nativo** — não é um chatbot único com prompts longos;
   é um time de agentes coordenado por orquestrador. UX melhor, custo
   menor (cada agente tem prompt curto e foco específico).
2. **Tool calling tipado** — ferramentas declaradas em schema (JSON ou
   Pydantic), executadas com retry/timeout, observáveis.
3. **Eval-first** — toda mudança em prompt/agente passa por suite de
   cenários antes de entrar em prod.
4. **White-label** — widget customizável, domínio próprio, e-mails com
   marca do tenant.
5. **Conformidade**: LGPD, GDPR, SOC2 prep desde o dia 1.

---

## 2. Casos de uso oficiais (templates iniciais)

A plataforma inclui templates prontos que o builder pode clonar:

1. **Banco/Fintech** (réplica do projeto-origem):
   `triage → credit → interview → exchange`.
2. **E-commerce**: `triage → order_status → returns → upsell`.
3. **Saúde**: `triage → scheduling → results → billing`.
4. **Educação**: `enrollment → financial → support → library`.
5. **Cobrança**: `identify → negotiation → payment_plan → confirmation`.

Cada template entrega: blueprint de agentes em YAML, prompts, schemas
das ferramentas e cenários de eval.

---

## 3. Modelo de dados

Esquema PostgreSQL com isolamento de tenant via **Row-Level Security
(RLS)**. Toda tabela de tenant carrega `tenant_id UUID` e tem policy
`USING (tenant_id = current_setting('app.tenant_id')::uuid)`.

### 3.1 Núcleo organizacional

```sql
tenants (
  id UUID PK,
  slug TEXT UNIQUE,           -- 'acme'
  name TEXT,
  plan TEXT,                  -- 'free' | 'starter' | 'pro' | 'enterprise'
  data_region TEXT,           -- 'br-sp' | 'us-east' | 'eu-west'
  created_at, updated_at
)

users (
  id UUID PK,
  tenant_id UUID FK,
  email CITEXT UNIQUE,
  password_hash TEXT,         -- argon2id
  role TEXT,                  -- 'owner' | 'admin' | 'builder' | 'viewer'
  totp_secret_encrypted TEXT, -- 2FA opcional
  created_at, last_login_at
)

workspaces (
  id UUID PK,
  tenant_id UUID FK,
  name TEXT,
  settings JSONB              -- branding, idiomas, etc.
)

api_keys (
  id UUID PK,
  tenant_id UUID FK,
  workspace_id UUID FK,
  key_hash TEXT,              -- guardar só hash
  prefix TEXT,                -- 'bk_live_abcd1234' (mostrado no UI)
  scopes TEXT[],
  expires_at,
  last_used_at
)
```

### 3.2 Definição de agentes

```sql
agent_blueprints (
  id UUID PK,
  workspace_id UUID FK,
  name TEXT,
  version INT,                -- versionamento explícito
  system_prompt TEXT,
  intents TEXT[],             -- intents que ele aceita
  required_inputs JSONB,      -- ex.: [{name:'cpf', type:'string', validator:'cpf_br'}]
  tools UUID[],               -- FK para tools
  metadata JSONB,
  is_published BOOLEAN,
  created_by UUID FK users
)

tools (
  id UUID PK,
  workspace_id UUID FK,
  name TEXT,                  -- 'get_credit_limit'
  description TEXT,           -- mostrado ao LLM
  schema JSONB,               -- JSON Schema dos params
  implementation TEXT,        -- 'http' | 'webhook' | 'sql' | 'code'
  config JSONB,               -- url, headers, query, código sandboxed
  timeout_ms INT,
  retry_policy JSONB
)

routers (
  id UUID PK,
  workspace_id UUID FK,
  agents UUID[],              -- ordem de prioridade
  intent_classifier_model TEXT,
  fallback_message TEXT,
  meta_commands JSONB         -- tokens para cancelar/ajuda/etc.
)
```

### 3.3 Runtime de conversação

```sql
conversations (
  id UUID PK,
  tenant_id UUID FK,
  workspace_id UUID FK,
  channel TEXT,               -- 'widget' | 'whatsapp' | 'api' | 'email'
  end_user_id UUID FK,        -- usuário final do tenant
  started_at, ended_at,
  ended_reason TEXT,          -- 'goodbye' | 'timeout' | 'handoff' | 'error'
  metadata JSONB
)

messages (
  id UUID PK,
  conversation_id UUID FK,
  role TEXT,                  -- 'user' | 'assistant' | 'system' | 'tool'
  content TEXT,
  agent_id UUID FK,           -- qual agente respondeu
  tool_calls JSONB,           -- se assistant chamou ferramentas
  tokens_input INT,
  tokens_output INT,
  latency_ms INT,
  created_at
)

end_users (
  id UUID PK,
  tenant_id UUID FK,
  external_id TEXT,           -- id no sistema do cliente
  attributes JSONB,           -- nome, e-mail, atributos do cliente
  pii_encrypted JSONB         -- campos sensíveis com pgcrypto
)
```

### 3.4 Billing & uso

```sql
subscriptions (
  id UUID PK,
  tenant_id UUID FK UNIQUE,
  stripe_subscription_id TEXT,
  plan TEXT,
  status TEXT,                -- 'active' | 'past_due' | 'canceled'
  current_period_end TIMESTAMPTZ
)

usage_events (
  id BIGSERIAL PK,
  tenant_id UUID FK,
  metric TEXT,                -- 'message' | 'tokens_input' | 'tokens_output' | 'tool_call'
  amount BIGINT,
  conversation_id UUID,
  agent_id UUID,
  occurred_at TIMESTAMPTZ
)
-- Agregação diária por tenant para billing rápido:
CREATE MATERIALIZED VIEW usage_daily AS
SELECT tenant_id, date_trunc('day', occurred_at) AS day, metric, sum(amount)
FROM usage_events GROUP BY 1,2,3;
```

### 3.5 Auditoria

```sql
audit_log (
  id BIGSERIAL PK,
  tenant_id UUID,
  actor_user_id UUID,
  actor_ip INET,
  action TEXT,                -- 'agent.published', 'tool.executed', 'data.exported', ...
  target_type TEXT,
  target_id UUID,
  payload JSONB,              -- redacted: nunca contém PII bruto
  created_at TIMESTAMPTZ
)
```

---

## 4. Arquitetura técnica

### 4.1 Visão de alto nível

```
                  ┌─────────────────────────────────────────┐
                  │            Edge (Cloudflare)            │
                  │  WAF · rate limit · TLS · static cache  │
                  └────────────────┬────────────────────────┘
                                   │
            ┌──────────────────────┼──────────────────────┐
            │                      │                      │
        ┌───▼────┐            ┌────▼─────┐          ┌─────▼─────┐
        │ Widget │            │ Builder  │          │ Public    │
        │  CDN   │            │  Next.js │          │ docs site │
        └───┬────┘            └────┬─────┘          └───────────┘
            │                      │
            │  REST + SSE/WS       │  REST + SSE
            └──────────┬───────────┘
                       │
              ┌────────▼─────────┐
              │   API Gateway    │  (FastAPI; auth, RLS, routing)
              └────────┬─────────┘
                       │
       ┌───────────────┼───────────────┐
       │               │               │
┌──────▼─────┐  ┌──────▼──────┐  ┌─────▼──────┐
│ Orchestrator│ │ Tool Runner │  │  LLM Pool  │
│   workers   │ │   workers   │  │   gateway  │
└──────┬──────┘ └──────┬──────┘  └─────┬──────┘
       │               │               │
       └───────────────┼───────────────┘
                       │
       ┌───────────────┼─────────────────────────┐
       │               │                         │
┌──────▼──────┐  ┌─────▼─────┐  ┌────────────────▼────────┐
│ PostgreSQL  │  │   Redis   │  │  Object storage (S3)    │
│  + RLS      │  │ sessions  │  │  exports, attachments   │
│  + pgcrypto │  │ cache     │  │                         │
└─────────────┘  └───────────┘  └─────────────────────────┘
```

### 4.2 Componentes

| Componente        | Função                                            | Stack                                |
| ----------------- | ------------------------------------------------- | ------------------------------------ |
| API Gateway       | Recebe HTTP; auth, RLS, rate limit                | FastAPI + asyncpg                    |
| Orchestrator      | Conversa, troca de agente, meta-comandos          | Python (mesmo padrão do MVP atual)   |
| Tool Runner       | Executa ferramentas (HTTP, código sandboxed)      | Workers ARQ ou Celery                |
| LLM Gateway       | Pool de provedores, cache, fallback, circuit-bk   | Python (mesmo `LLMGateway` evoluído) |
| Builder UI        | Painel web de configuração                        | Next.js 14 + Tailwind + shadcn       |
| Widget            | Bolha de chat embedável                           | React + Vite, bundle ≤ 30KB gzipped  |
| Eval runner       | Cron diário rodando cenários de cada workspace    | Python                               |
| Stream relay      | Streaming SSE/WS para token-by-token              | FastAPI + Redis pub/sub              |
| Webhook delivery  | Eventos saindo (conversation.ended, tool.failed)  | Workers com retry exponential        |

### 4.3 Por que separar Orchestrator e Tool Runner

- Orchestrator é I/O leve (chama LLM, decide próximo agente). Roda
  como serviço web async stateless.
- Tool Runner pode rodar código arbitrário do cliente (com timeout e
  sandbox), faz chamadas externas com retries longos. Roda como
  worker; falha isolada não derruba conversa.

### 4.4 Fluxo de uma mensagem

1. Widget POST `/v1/conversations/{id}/messages` com `Authorization: Bearer <api_key>` ou cookie de end-user.
2. Gateway autentica, resolve `tenant_id`, seta `app.tenant_id` no
   conn (RLS ativa).
3. Recupera sessão do Redis. Se primeira mensagem, cria conversation no
   Postgres.
4. Orchestrator classifica intent → escolhe agente.
5. Agente monta prompt (system + histórico curto + tools disponíveis).
6. LLM Gateway responde (streaming). Se o LLM pediu tool call:
   - Tool Runner executa com timeout.
   - Resultado volta como mensagem `role=tool` → LLM continua.
7. Resposta final streamada para o cliente via SSE.
8. Mensagem persistida, `usage_events` registrado, webhook disparado
   se configurado.

### 4.5 Stack escolhida (e por quê)

| Camada            | Escolha                | Justificativa                                |
| ----------------- | ---------------------- | -------------------------------------------- |
| Backend           | Python 3.12 + FastAPI  | maturidade no ecossistema LLM, async nativo  |
| ORM               | SQLAlchemy 2 + asyncpg | tipos estáticos + performance                |
| Migrations        | Alembic                | padrão do ecosistema                         |
| Cache/sessions    | Redis 7                | TTL nativo, pub/sub, lua scripts             |
| Workers           | ARQ (Redis-based)      | mais leve que Celery, ótimo p/ async         |
| LLM               | OpenAI + Anthropic     | fallback entre eles; local Ollama opcional   |
| Frontend Builder  | Next.js 14 + App Router| SSR/streaming nativo, RSC                    |
| UI kit            | shadcn/ui + Tailwind   | componível, dono do código                   |
| Auth              | WorkOS ou Clerk        | SSO/SAML out-of-the-box para Enterprise      |
| Billing           | Stripe Billing         | meter API + portal hospedado                 |
| Observabilidade   | OpenTelemetry → Grafana| vendor-neutral                               |
| Infra             | AWS EKS + Terraform    | multi-região; ECS é alternativa cost-friendly|
| CI/CD             | GitHub Actions + ArgoCD| GitOps                                       |

---

## 5. APIs públicas

### 5.1 Endpoints REST principais (`/v1`)

```
# Conversations
POST   /v1/conversations                          # cria nova
GET    /v1/conversations/{id}
POST   /v1/conversations/{id}/messages            # envia user message
GET    /v1/conversations/{id}/stream              # SSE stream
POST   /v1/conversations/{id}/end                 # fecha

# Agents (config)
POST   /v1/workspaces/{ws}/agents
GET    /v1/workspaces/{ws}/agents
PATCH  /v1/workspaces/{ws}/agents/{id}
POST   /v1/workspaces/{ws}/agents/{id}/publish

# Tools
POST   /v1/workspaces/{ws}/tools
POST   /v1/workspaces/{ws}/tools/{id}/test        # dry-run

# Evals
POST   /v1/workspaces/{ws}/evals/run              # roda cenários
GET    /v1/workspaces/{ws}/evals/runs/{id}

# Webhooks
POST   /v1/workspaces/{ws}/webhooks
GET    /v1/workspaces/{ws}/webhooks/{id}/deliveries

# Admin / billing
GET    /v1/usage?from=&to=&group_by=
GET    /v1/billing/portal                          # redireciona p/ Stripe Portal

# End-user data (LGPD)
GET    /v1/end-users/{id}/data                    # export
POST   /v1/end-users/{id}/forget                  # anonimização
```

### 5.2 Autenticação

- **API key** no header `Authorization: Bearer bk_live_...` para
  acesso server-to-server.
- **JWT de usuário do builder** (login UI) com refresh + revocation.
- **JWT de end-user** assinado pelo backend do cliente (claims:
  tenant, end_user_id, conversation_id) — para o widget falar direto.

### 5.3 Config-as-code (GitOps de agentes)

Todo agente, tool e router pode ser exportado/importado como YAML:

```yaml
# agents/credit.v3.yaml
apiVersion: agentkit/v1
kind: AgentBlueprint
metadata:
  name: credit
  workspace: acme/sales
spec:
  system_prompt: |
    Você é o agente de crédito do Banco Ágil...
  intents: [credit_limit, request_increase]
  tools: [get_credit_limit, request_limit_increase]
  required_inputs:
    - name: cpf
      type: string
      validator: cpf_br
```

CLI `agentkit apply -f agents/` aplica o diretório (idempotente,
detecta drift, mostra diff antes). Equipes mais maduras usam o CLI no
CI do próprio repo para versionar a configuração dos agentes em git.

### 5.4 SDKs

- **Python**: `pip install agentkit-sdk`
- **JavaScript/TypeScript**: `npm install @agentkit/sdk`
- **CLI**: `npx @agentkit/cli init` cria projeto template.

Exemplo TS:
```ts
import { AgentKit } from "@agentkit/sdk";
const ak = new AgentKit({ apiKey: process.env.AGENTKIT_KEY });
const convo = await ak.conversations.create({ endUser: { externalId: "u_123" } });
for await (const chunk of ak.conversations.stream(convo.id, "Quero meu pedido")) {
  process.stdout.write(chunk.delta);
}
```

### 5.5 Webhooks

Eventos enviados ao endpoint configurado, com HMAC SHA-256:

```
conversation.created
conversation.message.created
conversation.handoff_requested
conversation.ended
tool.execution.failed
usage.threshold.crossed
```

Cada delivery vira uma linha em `webhook_deliveries` com retry
exponencial (1s → 60s → 5min → 1h → 6h → 24h, máx 6 tentativas).

---

## 6. Builder UI (Next.js 14)

### 6.1 Páginas

```
/                       # landing
/signup                 # cria tenant + workspace
/login
/[workspace]/dashboard
/[workspace]/agents
/[workspace]/agents/new
/[workspace]/agents/[id]/edit
/[workspace]/tools
/[workspace]/tools/[id]/edit
/[workspace]/conversations
/[workspace]/evals
/[workspace]/settings
/[workspace]/billing
/[workspace]/api-keys
```

### 6.2 Components-chave

- `<AgentEditor>`: formulário com nome, system prompt (editor com
  syntax highlight), intents (multi-tag), tools (multi-select),
  required inputs (drag-and-drop). Preview lateral com simulador.
- `<ToolEditor>`: tabs `HTTP / SQL / Code / Webhook`. Cada um com
  schema editor (JSON Schema) e dry-run.
- `<ConversationPlayer>`: replay com timeline (mensagens, tool calls,
  latência por mensagem). Filtros por agent, channel, end_user.
- `<EvalRunner>`: lista de cenários, botão "rodar agora", relatório
  com diff entre execuções.
- `<AnalyticsCharts>`: usage por dia, custo, agent activity, top
  intents, fallback rate.

### 6.3 Princípios visuais

- Tipografia clara, espaços generosos, cores neutras (zinc), accent
  azul para CTA.
- Dark mode default; respeitar `prefers-color-scheme`.
- Acessível: WCAG AA, foco visível, contraste ≥ 4.5.
- 100% responsive.

---

## 7. Widget embedável

### 7.1 Características

- 1 linha de instalação:
  ```html
  <script src="https://cdn.agentkit.io/widget.js"
          data-public-key="pk_live_..." defer></script>
  ```
- Self-hosting do JWT do end-user via endpoint do backend do cliente.
- Customização via `data-*`: `data-primary-color`, `data-position`,
  `data-greeting`.
- Persistência da conversa no `localStorage` (id da conversation +
  JWT curto).
- Acessibilidade: ARIA roles, controlável por teclado.
- Bundle ≤ 30KB gzipped (sem React no caller — empacotar preact no
  bundle do widget).
- Streaming de tokens com SSE; fallback para polling se proxy bloquear.

### 7.2 Integrações canal extra

- WhatsApp (via Meta Cloud API ou Twilio).
- E-mail (inbound IMAP, outbound SMTP).
- Slack (app do tenant).
- API direta (sem widget).

Adapter `ChannelAdapter` converte entre formato externo e
`messages` interno.

### 7.3 Handoff humano

Toda conversa pode ser transferida para um humano. Modelo:

- O agente sinaliza handoff: `tool_call={name: "handoff", reason:
  "...", priority: "low|normal|high"}`. Ou via meta-comando do
  end-user: "quero falar com uma pessoa".
- Sistema cria um `handoff_request` (tabela própria) e dispara webhook
  `conversation.handoff_requested` para o tenant.
- Status `awaiting_human` → mensagens novas do end-user ficam na fila.
- Agente humano usa um console (ou integração com Zendesk/Intercom)
  para responder. Cada mensagem dele vai como `role=assistant,
  human=true`.
- Encerramento: humano marca como resolvido → conversa volta para o
  agente ou termina.
- SLA por prioridade configurável (`high` = pager para o tenant).

---

## 8. LLM Gateway

### 8.1 Responsabilidades

- Pool com múltiplos provedores e modelos por tenant.
- Roteamento por custo/qualidade: `gpt-4o-mini` para classificação,
  `gpt-4o` ou `claude-sonnet` para resposta principal, `gpt-4o-mini`
  para reescrita de tom.
- Streaming token-a-token.
- Cache literal e semântico (embeddings + cosine ≥ 0.95).
- Circuit breaker por provedor.
- Budget guard: corta requisição se o tenant ultrapassou cota mensal.
- Redação automática de PII no prompt enviado ao LLM (CPF, e-mail,
  telefone) — exceto quando explicitamente marcado em config.

### 8.2 Tool calling

Usar a API nativa de tool calling do provedor (OpenAI
`tool_choice="auto"`, Anthropic `tools=[...]`). Validar resposta
contra o JSON Schema da tool antes de executar.

### 8.3 Versionamento e deploy gradual de agentes

- Cada `agent_blueprint` tem `version INT` incremental. Publicar não
  sobrescreve: cria nova versão.
- Coluna `traffic_split JSONB`: `{"v3": 0.9, "v4": 0.1}` permite canary
  por tenant.
- Roteador escolhe versão por hash do `conversation.id` → distribuição
  consistente dentro da mesma conversa.
- `rollback`: 1 clique no Builder UI volta o `traffic_split` para a
  versão estável anterior.
- Métrica `agentkit_agent_version_pass_rate{agent,version}` permite
  comparar versões com cenários de eval.

### 8.4 Prompt template

```jinja2
Você é o agente "{{agent.name}}" do workspace "{{workspace.name}}".
{{agent.system_prompt}}

REGRAS GLOBAIS DA PLATAFORMA (não negociáveis):
- Você NUNCA diz "não posso ajudar". Se o pedido foge dos serviços
  configurados, ofereça as opções disponíveis.
- Não invente dados — use apenas o resultado das ferramentas.
- Respostas curtas (≤ 3 frases) e em {{workspace.language}}.
- Se a mensagem é confusa, peça clarificação prática.

Serviços disponíveis no momento: {{available_agents | join(", ")}}.
Ferramentas: {{tools | tojson}}.
Histórico recente:
{% for m in history[-6:] %}
{{m.role}}: {{m.content}}
{% endfor %}
```

---

## 9. Segurança e compliance

### 9.1 Identidade
- Hash de senha: argon2id (work factor 3+, memory 64MB).
- 2FA via TOTP (otplib) — obrigatório no plano Enterprise.
- SSO (SAML, OIDC) via WorkOS para Enterprise.
- Sessões web com cookies `Secure HttpOnly SameSite=Lax`.

### 9.2 Isolamento de tenant
- RLS em todas as tabelas de tenant.
- `current_setting('app.tenant_id')` setado pelo gateway por request.
- Em queries com `bypass` (admin), log obrigatório.

### 9.3 Criptografia
- TLS 1.3 obrigatório (Cloudflare).
- At-rest: AES-256 (RDS encryption) + pgcrypto para colunas PII.
- Chaves gerenciadas em AWS KMS, rotação anual.

### 9.4 LGPD / GDPR
- Endpoints `GET /v1/end-users/{id}/data` (portabilidade) e
  `POST /v1/end-users/{id}/forget` (esquecimento).
- Data Processing Addendum (DPA) padrão em `docs/legal/dpa.md`.
- Cookie banner no widget (configurável por região).
- Data residency: `tenant.data_region` controla qual cluster atende
  (br-sp / us-east / eu-west).

### 9.5 SOC2 prep
- Audit log imutável (append-only) com hash chain.
- Backups diários cifrados, retenção 30 dias, restore drill trimestral.
- Vulnerability scan (Trivy) em todo build de imagem.
- Penetration test anual (3rd party).
- Política de acesso: least privilege, MFA obrigatório, revisão
  trimestral.

### 9.6 Internacionalização, timezone e acessibilidade
- **Idiomas**: `workspace.settings.language` (default `pt-BR`); o
  `LLMGateway` injeta no prompt e o widget carrega `i18n/{lang}.json`.
- **Timezone**: cada `end_user` carrega `timezone IANA` (default
  `America/Sao_Paulo`); o agente formata datas/horários conforme.
- **Acessibilidade**: widget WCAG AA; foco visível; suporte completo a
  leitor de tela; navegação por teclado (Tab/Esc/Enter).

### 9.7 Sandbox de código (Tool Runner — `implementation=code`)
- Execução em container efêmero (gVisor / Firecracker).
- CPU 100m, memória 128MB, timeout 5s.
- Sem rede salvo lista de hosts permitidos pelo tenant.
- Linguagens: Python 3.12 e Node 20 (subset).

---

## 10. Observabilidade

### 10.1 Logs
- `structlog` JSON com `request_id`, `tenant_id`, `conversation_id`,
  `agent_id`.
- Nunca logar PII bruto; redactor central em
  `lib/log_redact.py` (CPF, e-mail, telefone, cartão).
- Centralizados em Loki ou OpenSearch.

### 10.2 Métricas (Prometheus)
- `agentkit_requests_total{tenant,endpoint,status}`
- `agentkit_llm_latency_seconds{provider,model}`
- `agentkit_tool_executions_total{tool,outcome}`
- `agentkit_conversation_duration_seconds`
- `agentkit_handoff_total{reason}`
- `agentkit_eval_pass_rate{workspace}`

### 10.3 Tracing
- OpenTelemetry; span de cada request → orchestrator → llm → tool.
- Sampling: 100% para erros, 10% para sucesso (config por tenant).

### 10.4 Alertas (PagerDuty)
- p95 `/v1/conversations/*/messages` > 3s por 5min → warn.
- LLM provider error rate > 5% por 1min → page.
- Postgres replica lag > 30s → page.
- Tenant uso > 90% do limite → notificação (não pager).

---

## 11. Billing (Stripe)

### 11.1 Modelagem

- **Plans** (Stripe Products):
  - **Free**: 100 mensagens/mês, 1 workspace, 2 agentes.
  - **Starter** ($49/mês): 5k mensagens, 3 workspaces, 5 agentes,
    branding básico.
  - **Pro** ($299/mês): 50k mensagens, ilimitado, branding total,
    evals automáticos.
  - **Enterprise** (sob consulta): SLA 99.9%, SSO/SAML, data
    residency, white-label completo.
- Add-ons: pacote de mensagens extras, tokens extras, agentes extras.

### 11.2 Metering
- `usage_events` agregado a cada hora → Stripe Meter API.
- Hard cap configurável por tenant (corta serviço quando estoura).
- Soft cap envia e-mail/webhook ao atingir 80% e 100%.

### 11.3 Faturamento e cobrança
- Stripe Billing Portal para auto-serviço.
- Invoice mensal + reconciliação por usage.
- Dunning automático para `past_due`.

---

## 12. DevOps e infra

### 12.1 Repositórios

Monorepo (turborepo) ou polirrepo:

```
agentkit/
├── apps/
│   ├── api/              # FastAPI
│   ├── workers/          # ARQ workers
│   ├── builder/          # Next.js builder UI
│   ├── widget/           # React widget
│   └── docs/             # Docusaurus
├── packages/
│   ├── sdk-ts/
│   ├── sdk-py/
│   ├── shared-types/
│   └── ui/
├── infra/
│   ├── terraform/        # AWS infra
│   ├── helm/             # k8s charts
│   └── grafana/          # dashboards
├── evals/                # cenários compartilhados
└── docs-md/              # ADRs, runbooks
```

### 12.2 Ambientes
- `dev` (compartilhado, restored daily).
- `staging` (espelho de prod, dados sintéticos).
- `prod` multi-AZ + read-replica + cold standby cross-region.

### 12.3 Pipeline (GitHub Actions + ArgoCD)
1. Push → `lint + type + tests + build + security scan` por app.
2. Tag → push image, helm chart bump.
3. ArgoCD sincroniza staging automaticamente.
4. Smoke test E2E em staging.
5. Promote to prod manual (com approval).
6. Canary 5% → 25% → 100% via Flagger.

### 12.4 Backup e DR
- RDS automated backups diários + PITR 7 dias.
- Snapshot semanal arquivado por 90 dias.
- Restore drill mensal em ambiente "dr-test".
- RTO 1h, RPO 5min para prod.

### 12.5 Custos
Tabela alvo (estimativa por 1000 conversas/dia):
- Compute: ~$120/mês
- DB (db.t4g.medium + replica): ~$100/mês
- Redis (cache.t4g.small): ~$25/mês
- LLM: ~$300/mês (gpt-4o-mini majoritário)
- CDN + tráfego: ~$30/mês
- Observability stack: ~$80/mês
**Total ~$650/mês para 30k conversas/mês.** Margem >70% no plano Pro.

---

## 13. Roadmap

### Fase MVP (semana 1-12) — "First customer pays"
- Multi-tenant + auth + RLS.
- Modelo de dados completo.
- Orchestrator + 3 agentes default (triagem, resposta, encerramento).
- Builder UI: criar/editar agente, criar tool HTTP, ver conversas.
- Widget mínimo (sem streaming, polling 1s).
- Billing Stripe com Free + Starter.
- Template "E-commerce" pronto.

### Fase Beta (semana 13-24) — "10 paying customers"
- Streaming SSE no widget.
- Tool Runner com sandbox de código.
- Eval framework + cenários.
- Webhooks com retry.
- SDK TS + Python.
- Plano Pro liberado.
- SOC2 Type I em andamento.

### Fase GA (semana 25-36) — "100 paying customers"
- Multi-região (br-sp + us-east).
- SSO/SAML, SCIM provisioning.
- WhatsApp + Slack adapters.
- Templates: Saúde, Educação, Banco, Cobrança.
- Marketplace de templates (revenue share com builders).
- Plano Enterprise liberado.
- SOC2 Type II auditoria.

### Pós-GA (mês 9+)
- Voz (Whisper + TTS).
- RAG nativo (Postgres pgvector ou Weaviate).
- Multilíngue automático.
- Conector low-code (HubSpot, Salesforce, Zendesk).
- Modelos locais para clientes regulados (Llama, Mistral via Ollama).

---

## 14. Critérios de sucesso

| Indicador                                | Alvo no GA |
| ---------------------------------------- | ---------- |
| Tempo de onboarding (signup → 1ª convo)  | < 10 min   |
| p95 latência `/messages` (LLM ligado)    | < 2s       |
| Uptime mensal                            | ≥ 99.9%    |
| Cobertura de testes                      | ≥ 90%      |
| Eval pass rate dos templates oficiais    | 100%       |
| Taxa de agente recusando ("não posso")   | 0%         |
| Custo médio LLM por conversa             | < $0.02    |
| NPS dos builders                         | ≥ 50       |
| Churn mensal                             | < 3%       |

---

## 15. Princípios de execução (para a IA que vai construir)

1. **Comece pelo skeleton end-to-end**: API auth → criar agente →
   widget envia mensagem → resposta volta. Não invista em features
   antes desse loop existir.
2. **Tudo configurável por YAML**: agentes, tools, prompts. UI vem
   depois do CLI/YAML.
3. **Templates oficiais são os melhores testes**: se um template
   quebra, a plataforma quebrou.
4. **Eval-first sempre**: cada feature de prompt/agente vem com
   cenários. CI bloqueia regressão.
5. **Multi-tenant desde o primeiro commit**: nunca é "adicionar
   depois". Postgres com RLS desde o dia 1.
6. **Não confiar em input**: tudo do widget passa por validação
   server-side. Schemas Pydantic em todos os endpoints.
7. **Custo é feature**: cada conversa carrega seu custo no log
   (`tokens_input`, `tokens_output`, `tool_call_count`). Dashboards
   sempre por tenant.
8. **Sem black box**: toda decisão do agente (intent escolhido, tools
   chamadas, mudança de agente) é gravada em `messages.metadata` e
   visualizada no replay.
9. **Falha gracefully**: timeout do LLM → mensagem amigável + log;
   tool errada → tentar próximo agente; tenant past_due → mensagem
   "serviço suspenso temporariamente" para o end-user.
10. **Documentação na PR**: toda PR atualiza README, OpenAPI ou ADR
    quando muda contrato/decisão.

---

## 16. Pontos abertos (decidir no início do projeto)

Antes de codar, os builders/founders precisam responder:

1. **Single-region ou multi-region desde o dia 1?** Padrão sugerido:
   single-region (br-sp) com tabela `tenants.data_region` já pronta
   para expansão.
2. **Schema-per-tenant ou RLS?** RLS é mais simples para milhares de
   tenants pequenos. Schema-per-tenant ajuda clientes Enterprise. O
   plano Enterprise pode ter cluster dedicado.
3. **Auth via Clerk/WorkOS vs próprio?** Próprio dá controle total e
   sem fee por usuário, mas SSO/SAML é trabalho. Recomendado: WorkOS
   ($/MAU) só nos Enterprise.
4. **Workers ARQ vs Celery?** ARQ é mais leve, async nativo, menos
   features. Celery tem ecossistema. Para começar, ARQ.
5. **Sandbox de código: gVisor (k8s nativo) ou Firecracker (mais
   isolado, mais complexo)?** Para MVP, container Docker padrão com
   limites cgroup é suficiente. gVisor entra na fase Beta.
6. **Vector store?** Posterga; quando RAG entrar, começar com
   `pgvector` (sem nova dependência operacional).

---

## 17. Checklist mínimo do "MVP funcional"

- [ ] `docker-compose up` sobe api + postgres + redis e responde
      `/v1/health` 200.
- [ ] `make seed` cria tenant + user + workspace + agente "echo" +
      conversation de teste.
- [ ] Widget integrado em `docs/example.html` envia mensagem e recebe
      resposta do agente echo.
- [ ] Trocar `system_prompt` do agente via API muda a resposta na
      próxima mensagem.
- [ ] Criar uma tool HTTP que retorna `{"now": <timestamp>}` e o
      agente sabe chamá-la quando o usuário pergunta "que horas são?".
- [ ] Endpoint `GET /v1/usage` retorna a contagem de mensagens.
- [ ] Stripe sandbox conectado, criação de subscription Free funciona.
- [ ] Login via e-mail/senha + 2FA opcional.
- [ ] Logs JSON com `tenant_id` em todas as linhas.
- [ ] CI verde, cobertura ≥ 80%.

Quando os 10 itens acima estiverem feitos, o produto é vendável para o
primeiro design partner. Tudo daí pra frente é roadmap.
