# Documentacao Tecnica - Agente Bancario Inteligente

## Visao Geral

O **Agente Bancario Inteligente** é um sistema de atendimento digital que utiliza Inteligencia Artificial para simular um atendente bancario virtual. O sistema oferece servicos como autenticacao, consulta de limite de credito, solicitacao de aumento, cotacao de moedas e entrevista financeira para atualizacao de score.

---

## Arquitetura do Sistema

```
┌─────────────────────────────────────────────────────────────────┐
│                         Cliente (Frontend)                        │
│                 Next.js (chat) / API Consumer                     │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                         API Layer                                 │
│                     FastAPI (routes.py)                           │
│         Endpoints REST com validacao via Pydantic                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Orchestrator Layer                           │
│                     (orchestrator.py)                             │
│         Gerencia estado da conversa e roteia mensagens           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│   Triagem    │   │   Credito    │   │  Entrevista  │
│   Agent      │   │   Agent      │   │    Agent     │
└──────────────┘   └──────────────┘   └──────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Service Layer                               │
│  AuthService │ ScoreService │ LLMService │ SignupService │ ...   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Data Layer                                 │
│  Repositorios -> SQLAlchemy async -> SQLite / Postgres           │
│  clients | score_limits | limit_requests | score_events          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Como Rodar o Projeto

### Pre-requisitos

- Python 3.11 ou superior
- pip (gerenciador de pacotes Python)
- Git

### Instalacao Passo a Passo

```bash
# 1. Clone o repositorio
git clone <url-do-repositorio>
cd IA-Agent-Tech-For-Humans-Back-end

# 2. Crie e ative um ambiente virtual
python -m venv venv

# Windows
.\venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

# 3. Instale as dependencias
pip install -r requirements.txt

# 4. Configure as variaveis de ambiente
cp .env.example .env
# Edite o arquivo .env conforme necessario
```

### Executando o Backend (API)

```bash
python app.py
```

A API estara disponivel em: `http://localhost:8000`
Documentacao Swagger: `http://localhost:8000/docs`

### Executando o Frontend (Next.js)

O front-end fica no repositorio `IA-Agent-Tech-For-Humans-Front-end`:

```bash
npm install
cp .env.example .env.local   # BACKEND_URL=http://localhost:8000
npm run dev
```

Interface disponivel em: `http://localhost:3000`

### Usando Docker

```bash
# Build da imagem
docker build -t agente-bancario .

# Executar container
docker run -p 8000:8000 agente-bancario

# Ou usando docker-compose
docker-compose up -d
```

---

## Logica do Agente

### Orquestrador (orchestrator.py)

O orquestrador é o cérebro do sistema. Ele gerencia o estado da conversa através de uma máquina de estados finita e roteia as mensagens para o agente apropriado.

#### Estados da Conversa

```python
class ConversationState(Enum):
    WELCOME = "welcome"                    # Estado inicial
    COLLECTING_CPF = "collecting_cpf"      # Aguardando CPF
    COLLECTING_BIRTHDATE = "collecting_birthdate"  # Aguardando data nascimento
    AUTHENTICATED = "authenticated"        # Usuario autenticado
    CREDIT_LIMIT_FLOW = "credit_limit"     # Fluxo de limite
    CREDIT_INCREASE_FLOW = "credit_increase"  # Fluxo de aumento
    INTERVIEW_INCOME = "interview_income"  # Entrevista: renda
    INTERVIEW_EMPLOYMENT = "interview_employment"  # Entrevista: emprego
    INTERVIEW_EXPENSES = "interview_expenses"  # Entrevista: despesas
    INTERVIEW_DEPENDENTS = "interview_dependents"  # Entrevista: dependentes
    INTERVIEW_DEBTS = "interview_debts"    # Entrevista: dividas
    EXCHANGE_FROM = "exchange_from"        # Cambio: moeda origem
    EXCHANGE_TO = "exchange_to"            # Cambio: moeda destino
    GOODBYE = "goodbye"                    # Despedida
```

#### Fluxo de Transicoes

```
WELCOME
    │
    ▼
COLLECTING_CPF ──────────────────────────────────────────┐
    │                                                    │
    ▼                                                    │
COLLECTING_BIRTHDATE                                     │
    │                                                    │
    ▼                                                    │
AUTHENTICATED ◄──────────────────────────────────────────┘
    │
    ├──► CREDIT_LIMIT_FLOW ──► AUTHENTICATED
    │
    ├──► CREDIT_INCREASE_FLOW ──► AUTHENTICATED (ou INTERVIEW se negado)
    │
    ├──► INTERVIEW_INCOME ──► INTERVIEW_EMPLOYMENT ──► ...
    │         └──► ... ──► INTERVIEW_DEBTS ──► AUTHENTICATED
    │
    ├──► EXCHANGE_FROM ──► EXCHANGE_TO ──► AUTHENTICATED
    │
    └──► GOODBYE
```

### Agentes Especializados

#### 1. Agente de Triagem (triagem.py)

**Responsabilidade**: Autenticacao do usuario

**Funcionamento**:
1. Recebe CPF do usuario (com ou sem formatacao)
2. Normaliza o CPF (remove pontos e tracos)
3. Valida os digitos verificadores (`src/utils/cpf.py`) antes de consultar a base
4. Busca o cliente no repositorio
4. Valida data de nascimento
5. Gera token JWT em caso de sucesso
6. Controla tentativas (maximo 3)

**Deteccao de Intencao**:
- Regras por palavra inteira primeiro (0 ms); LLM (se configurado) apenas quando as regras nao classificam
- Intents: `credit_limit`, `request_increase`, `exchange_rate`, `interview`, `greeting`, `goodbye`, `confirm`, `reject`, `off_topic`
- Detalhes em `docs/llm-intent-architecture.md` e `docs/arquitetura-hibrida-v2.md`

#### 2. Agente de Credito (credito.py)

**Responsabilidade**: Consulta e aumento de limite

**Funcionamento - Consulta**:
1. Recebe CPF do token JWT
2. Busca score do cliente
3. Le o limite concedido, persistido no cliente
4. Consulta a faixa de score para o teto que aquele score sustenta
5. Retorna limite atual, score e teto. Nao existe "disponivel": o MVP nao tem
   extrato de compras, e um percentual fixo seria um numero inventado

**Funcionamento - Aumento**:
1. Recebe o valor solicitado
2. Compara com o limite atual e com o teto da faixa de score
3. Ate o teto: aprovado, e o limite persistido passa a ser o valor pedido
4. Entre o teto e 1,5x o teto, com score >= 600: `pending_analysis` (registrado,
   limite inalterado)
5. Acima disso: negado, com oferta de entrevista
6. Registra o pedido na tabela `limit_requests` com o motivo da decisao e o score
   do momento

#### 3. Agente de Entrevista (entrevista.py)

**Responsabilidade**: Coleta de dados financeiros e calculo de score

**Dados Coletados**:
- Renda mensal
- Tipo de emprego (CLT, Autonomo, MEI, Publico, Desempregado)
- Despesas mensais
- Numero de dependentes
- Existencia de dividas

**Calculo do Score**:
```python
componente_renda = (renda / (despesas + 1)) * 30
componente_emprego = PESO_EMPREGO[tipo]  # 0 a 300 pontos
componente_dependentes = PESO_DEPENDENTES[quantidade]  # 30 a 100 pontos
componente_dividas = PESO_DIVIDAS[tem_dividas]  # -100 ou +100

score_final = clamp(soma_componentes, 0, 1000)
```

#### 4. Agente de Cambio (cambio.py)

**Responsabilidade**: Cotacao de moedas em tempo real

**Funcionamento**:
1. Recebe moeda de origem e destino
2. Consulta API externa (exchangerate-api.com)
3. Retorna taxa de conversao atualizada
4. Implementa cache de 5 minutos
5. Fallback para taxas pre-definidas se API falhar

**Moedas Suportadas**: USD, EUR, GBP, JPY, ARS, BRL

---

## Rotas da API

### Endpoints Publicos

| Metodo | Rota | Descricao |
|--------|------|-----------|
| `GET` | `/health` | Health check (versao e se o LLM esta ativo) |
| `POST` | `/triage/authenticate` | Autentica usuario |
| `POST` | `/unified/init` | Inicializa orquestrador unificado |
| `POST` | `/unified/chat` | Envia mensagem para orquestrador |

### Endpoints Protegidos (requerem JWT)

| Metodo | Rota | Descricao |
|--------|------|-----------|
| `GET` | `/credit/limit` | Consulta limite de credito |
| `POST` | `/credit/request_increase` | Solicita aumento de limite |
| `POST` | `/interview/submit` | Submete entrevista financeira |
| `GET` | `/exchange` | Consulta cotacao de moedas |

### Detalhamento das Rotas

#### POST /triage/authenticate

**Request**:
```json
{
  "cpf": "123.456.789-01",
  "birthdate": "1990-05-15",
  "user_message": "quero ver meu limite"
}
```

**Response (sucesso)**:
```json
{
  "authenticated": true,
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "redirect_intent": "credit_limit",
  "remaining_attempts": 3
}
```

**Response (falha)**:
```json
{
  "authenticated": false,
  "token": null,
  "redirect_intent": null,
  "remaining_attempts": 2
}
```

#### GET /credit/limit

**Headers**: `Authorization: Bearer <token>`

**Response**:
```json
{
  "cpf": "12345678909",
  "current_limit": 5000.0,
  "max_limit_for_score": 15000.0,
  "score": 750
}
```

#### POST /credit/request_increase

**Headers**: `Authorization: Bearer <token>`

**Request**:
```json
{
  "new_limit": 20000.0
}
```

**Response (aprovado)**:
```json
{
  "cpf": "12345678909",
  "requested_limit": 20000.0,
  "status": "approved",
  "message": "Seu pedido de aumento foi aprovado!",
  "offer_interview": false
}
```

**Response (negado)**:
```json
{
  "cpf": "12345678909",
  "requested_limit": 50000.0,
  "status": "denied",
  "message": "Infelizmente nao podemos aprovar este valor.",
  "offer_interview": true,
  "interview_message": "Gostaria de atualizar seu perfil financeiro para aumentar suas chances?"
}
```

#### POST /unified/chat

**Request**:
```json
{
  "session_id": "uuid-da-sessao",
  "message": "Meu CPF é 123.456.789-01"
}
```

**Response**:
```json
{
  "session_id": "uuid-da-sessao",
  "message": "Obrigado! Agora preciso da sua data de nascimento.",
  "state": "collecting_birthdate",
  "authenticated": false,
  "token": null,
  "current_agent": "triage",
  "available_actions": ["informar_data_nascimento"],
  "redirect_suggestion": null
}
```

---

## Integracao com LLM

### Modos de Operacao

O sistema suporta dois modos de classificacao de intencao:

#### 1. Modo LangChain (USE_LANGCHAIN=true)

- Usa OpenAI (gpt-4o-mini) ou Anthropic (claude)
- Temperatura baixa (0.3) para respostas deterministicas
- Prompts otimizados para economia de tokens
- Fallback automatico para regras se API falhar

#### 2. Modo Regras (USE_LANGCHAIN=false)

- Classificacao por palavras-chave (palavra inteira, sem falsos positivos de substring)
- Sem dependencias externas
- Ideal para ambientes sem acesso a API

Mesmo com o LLM ligado, as regras rodam primeiro e o LLM so e consultado quando elas nao
classificam a mensagem. Chamadas ao LLM tem timeout curto (2,5 s intencao, 4 s humanizacao)
e caem no modo regras/templates automaticamente.

### Humanizacao de Respostas

O `LLMService` oferece funcionalidade de humanizacao que transforma respostas tecnicas em linguagem natural:

**Entrada tecnica**:
```
Limite atual: R$ 15.000,00. Disponivel: R$ 12.000,00.
```

**Saida humanizada**:
```
Ola Maria! Seu limite de credito atual é de R$ 15.000,00,
e voce ainda tem R$ 12.000,00 disponiveis para uso.
Posso ajudar com mais alguma coisa?
```

---

## Persistencia de Dados

### Banco relacional

Os CSVs do desafio deixaram de ser o banco e passaram a ser o **seed**. O que roda e
SQLAlchemy 2 async: `aiosqlite` local, `asyncpg` em producao, selecionado por
`DATABASE_URL`.

| Tabela | Descricao |
|--------|-----------|
| `clients` | Clientes: cpf, nome, nascimento, score, limite_atual, origem, is_demo_persona |
| `score_limits` | Faixas de score e o teto de limite de cada uma |
| `limit_requests` | Cada pedido de aumento, com status, motivo e o score do momento |
| `score_events` | Historico de mudanca de score, com a origem (entrevista, manual) |

### Camada de repositorios

Os agentes nunca importam SQLAlchemy: eles falam com `ClientRepository`,
`ScoreLimitRepository` e `LimitRequestRepository`, que devolvem dataclasses de dominio.
Trocar SQLite por Postgres, ou por um duble em teste, nao toca em regra de negocio.

Cada metodo abre e fecha sua propria unidade de trabalho (commit no sucesso, rollback em
qualquer excecao). Onde uma operacao precisa ser atomica de ponta a ponta — alterar o
score e gravar o evento que o explica — ela vive em um unico metodo, em uma transacao.

### Seed e reset

`scripts/seed.py` carrega os CSVs. Com `DEMO_RESET_ON_START=true` o `lifespan` roda o
seed a cada boot, o que e o comportamento desejado na demonstracao: o disco do plano
gratuito do Render e efemero de qualquer jeito, e todo visitante encontra a mesma base
limpa. Em producao, `false` e Postgres externo.

---

## Seguranca

### Autenticacao JWT

- Algoritmo: HS256
- Expiracao: 15 minutos (configuravel)
- Payload: CPF e nome do cliente
- Validacao em todos os endpoints protegidos

### Protecoes Implementadas

1. **Rate Limiting**: Maximo 3 tentativas de autenticacao
2. **Mascaramento de CPF**: Logs exibem apenas ultimos 4 digitos
3. **Validacao de Entrada**: Pydantic valida todos os inputs
4. **Filtro de Contexto**: Agente rejeita perguntas fora do escopo bancario

---

## Variaveis de Ambiente

| Variavel | Descricao | Padrao |
|----------|-----------|--------|
| `JWT_SECRET_KEY` | Chave secreta JWT | (obrigatoria) |
| `JWT_EXPIRATION_MINUTES` | Tempo expiracao token | 15 |
| `USE_LANGCHAIN` | Ativar classificacao LLM | false |
| `LLM_PROVIDER` | Provedor (openai/anthropic) | openai |
| `LLM_MODEL` | Modelo OpenAI | gpt-4o-mini |
| `ANTHROPIC_MODEL` | Modelo Anthropic | claude-haiku-4-5-20251001 |
| `LLM_INTENT_TIMEOUT_SECONDS` | Timeout da classificacao de intencao | 2.5 |
| `LLM_HUMANIZE_TIMEOUT_SECONDS` | Timeout da humanizacao | 4.0 |
| `SESSION_TTL_MINUTES` | Sessoes de chat ociosas sao descartadas apos | 30 |
| `MAX_AUTH_ATTEMPTS` | Tentativas de autenticacao antes de travar a sessao | 3 |
| `OPENAI_API_KEY` | Chave API OpenAI | - |
| `ANTHROPIC_API_KEY` | Chave API Anthropic | - |
| `EXCHANGE_API_URL` | URL API de cambio | api.exchangerate-api.com |
| `DATA_DIR` | Diretorio dos CSVs usados como seed | src/data |
| `DATABASE_URL` | SQLite local ou Postgres | sqlite+aiosqlite:///./data/banco_agil.db |
| `DEMO_RESET_ON_START` | Recria o banco pelo seed a cada boot | true |
| `DEMO_MODE` / `SIGNUP_ENABLED` | Personas e auto-cadastro | true / true |
| `CPF_PROVIDER` | `mock` (offline) ou `serpro` | mock |
| `RATE_LIMIT_ENABLED` | Limite de requisicoes por IP | true |
| `JSON_LOGS` | Log estruturado, filtravel por request_id | false |
| `LOG_LEVEL` | Nivel de log | INFO |

---

## Executando Testes

```bash
# Todos os testes
pytest

# Com cobertura
pytest --cov=src --cov-report=html

# Testes especificos
pytest tests/test_triagem.py -v
pytest tests/test_orchestrator.py -v
pytest tests/test_integration.py -v

# Testes de restricao de contexto
pytest tests/test_restrictions.py -v
```

---

## Deploy

### Render.com

O projeto inclui `render.yaml` configurado para deploy automatico:

```yaml
services:
  - type: web
    name: agente-bancario
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: python app.py
```

### Docker Production

```bash
docker build -t agente-bancario:prod .
docker run -d \
  -p 8000:8000 \
  -e JWT_SECRET_KEY=sua-chave-secreta \
  -e USE_LANGCHAIN=true \
  -e OPENAI_API_KEY=sk-xxx \
  agente-bancario:prod
```

---

## Dados de Teste

| CPF | Nome | Data Nascimento | Score | Limite (tabela score) |
|-----|------|-----------------|-------|-----------------------|
| 52998224725 | Maria Helena Santos | 15/05/1990 | 315 | R$ 1.000 |
| 71893456209 | João Pedro Oliveira | 22/03/1985 | 620 | R$ 8.000 |
| 89156734502 | Ana Carolina Lima | 08/11/1992 | 609 | R$ 8.000 |
| 34567891234 | Carlos Eduardo Souza | 30/07/1978 | 450 | R$ 3.000 |
| 89123456789 | Patricia Souza Nascimento | 14/06/1976 | 920 | R$ 50.000 |

Lista completa em `src/data/clientes.csv`. Os testes automatizados (`pytest`) usam uma base isolada em diretorio temporario e nao alteram esses arquivos.

---

## Estrutura de Pastas

```
IA-Agent-Tech-For-Humans-Back-end/
├── app.py                    # Ponto de entrada
├── requirements.txt          # Dependencias
├── Dockerfile               # Container
├── docker-compose.yml       # Orquestracao Docker
├── render.yaml              # Deploy Render
├── .env.example             # Template ambiente
│
├── docs/
│   ├── DESENVOLVIMENTO.md   # Jornada do desenvolvedor
│   ├── DOCUMENTACAO-TECNICA.md  # Esta documentacao
│   ├── arquitetura-hibrida-v2.md   # Arquitetura hibrida do orquestrador
│   ├── llm-intent-architecture.md  # Classificacao de intencao (regras + LLM)
│   └── otimizacao-tokens.md # Otimizacoes de tokens
│
├── src/
│   ├── main.py              # Configuracao FastAPI
│   ├── config.py            # Settings
│   │
│   ├── api/
│   │   └── routes.py        # Endpoints
│   │
│   ├── agents/
│   │   ├── orchestrator.py  # Orquestrador
│   │   ├── triagem.py       # Agente autenticacao
│   │   ├── credito.py       # Agente credito
│   │   ├── entrevista.py    # Agente entrevista
│   │   └── cambio.py        # Agente cambio
│   │
│   ├── services/
│   │   ├── auth_service.py  # JWT
│   │   ├── signup_service.py # Auto-cadastro
│   │   ├── cpf_provider.py   # Verificacao de CPF (mock / Serpro)
│   │   ├── address_service.py# Consulta de CEP (BrasilAPI)
│   │   ├── llm_service.py   # Integracao LLM
│   │   └── score_service.py # Calculo score
│   │
│   ├── models/
│   │   ├── domain.py        # Entidades
│   │   └── schemas.py       # Pydantic schemas
│   │
│   ├── utils/
│   │   ├── exceptions.py    # Excecoes
│   │   ├── logging_config.py # Logs
│   │   ├── formatting.py    # Formatacao R$ padrao brasileiro
│   │   ├── text_normalizer.py # Normalizacao (palavra inteira)
│   │   └── value_extractor.py # Extratores
│   │
│   └── data/
│       ├── clientes.csv     # seed
│       └── score_limite.csv  # seed
│
└── tests/
    ├── conftest.py          # Fixtures
    ├── test_triagem.py
    ├── test_credito.py
    ├── test_entrevista.py
    ├── test_cambio.py
    ├── test_orchestrator.py
    ├── test_conversation_ux.py  # Cenarios de conversa (intencao antes do login, cambio direto, escapes)
    ├── test_conversation_improvements.py  # Oferta respondida com valor, sessao expirada, resiliencia
    ├── test_intent_rules.py     # Classificacao por regras e fronteira de palavra
    ├── test_cpf.py              # Digitos verificadores, incluindo o CSV de producao
    ├── test_demo.py             # Personas e login em um clique
    ├── test_signup.py           # Auto-cadastro por endpoint e por conversa
    ├── test_observability.py    # Retomada de sessao, telemetria, request id
    └── test_prompt_injection.py # Guarda deterministico da humanizacao
```

---

## Verificacao de CPF

Nao existe API publica e gratuita que devolva nome e data de nascimento a partir de um
CPF no Brasil. As fontes legitimas (Serpro Consulta CPF / Datavalid, bureaus como
BigDataCorp ou Idwall) sao pagas e exigem contrato com CNPJ; as "gratuitas" que aparecem
em buscas sao bases vazadas, e usa-las viola a LGPD.

Por isso `src/services/cpf_provider.py` define uma porta com dois adaptadores:

| `CPF_PROVIDER` | Comportamento |
|----------------|---------------|
| `mock` (padrao) | Valida digitos verificadores. Offline, deterministico, responde "situacao cadastral desconhecida" — que e exatamente o que o sistema sabe sem consultar a Receita |
| `serpro` | Adaptador escrito contra o contrato publicado do Serpro. Exige `SERPRO_API_TOKEN`; qualquer falha de rede ou autorizacao degrada para o `mock` em vez de derrubar o cadastro |

A aritmetica roda antes da chamada externa, entao um CPF invalido nunca gasta uma
requisicao paga.

A integracao externa que **e** real e gratuita neste projeto e a consulta de CEP
(BrasilAPI): publica, sem chave e sem dado pessoal. Ela preenche cidade e estado no
auto-cadastro, e qualquer indisponibilidade deixa o endereco vazio sem bloquear o
cadastro.

---

## Seguranca

### Autenticacao

CPF + data de nascimento nao e autenticacao forte. E a restricao do desafio, e esta
documentada como tal. As mitigacoes:

- **Tentativas contadas por CPF, nao por sessao** (`AuthAttemptTracker`, compartilhado
  entre o chat e o endpoint). Abrir uma aba nova nao zera o contador de quem esta
  chutando CPF alheio.
- **Bloqueio com janela de expiracao** (`AUTH_LOCKOUT_MINUTES`): sem isso, tres erros de
  terceiros trancariam um CPF ate o processo reiniciar.
- **Rate limit por IP** em `/unified/chat` (60/min), `/triage/authenticate` (10/min) e
  `/signup` (5/min), desligavel por `RATE_LIMIT_ENABLED` — a suite de testes o desliga.
- **CPF mascarado em todo log** (`529.***.***-25`), via `src/utils/cpf.py`.
- **JWT de 15 minutos** para os endpoints diretos.

### Prompt injection

A humanizacao recebe a mensagem do cliente, entao e o ponto do sistema exposto a
injecao. O guarda e deterministico, nao uma instrucao no prompt — pedir ao modelo para
nao se deixar enganar e um pedido, nao um controle.

`LLMService._preserves_facts(tecnica, humanizada)` extrai valores em R$, datas, codigos
de moeda e numeros da resposta tecnica e exige que todos sobrevivam a reescrita; alem
disso, rejeita qualquer valor monetario que apareca so na versao humanizada. Se a
verificacao falhar, vale o template.

Consequencia: um modelo totalmente comprometido nao consegue dizer ao cliente que o
limite dele e R$ 1.000.000,00. `tests/test_prompt_injection.py` injeta um `LLMService`
sequestrado e verifica isso sem chamar LLM nenhum.

### Cabecalhos

No front (`next.config.mjs`): `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` negando camera,
microfone, geolocalizacao e pagamento, e `poweredByHeader` desligado.

Nao ha CSP de proposito: o `next/font` injeta estilos inline, e uma CSP com
`unsafe-inline` escrita sem testar cada build nao protegeria nada.

---

## Observabilidade

- **Request id**: um middleware gera (ou reaproveita) `X-Request-ID` e o propaga por
  `contextvars` para todos os logs daquele turno. Sem ele, investigar "a conversa do
  fulano travou" em um log concorrente e impossivel: as linhas de varias sessoes se
  intercalam.
- **Log estruturado**: `JSON_LOGS=true` troca o formato alinhado por JSON de uma linha
  por evento, filtravel por `request_id`. Sem dependencia nova: `json.dumps` no
  `format`.
- **Telemetria de turno**: `Orchestrator.process_message` mede o tempo do turno e se ele
  custou uma chamada ao modelo. `/health` expoe `turns_total`, `llm_turns_total` e
  `llm_turn_ratio`.

O contador existe para que a afirmacao "a maioria das mensagens nao chega ao modelo"
seja medida e nao estimada. A estimativa envelhece a cada regra nova de classificacao.

---

## Avaliacao do classificador

`evals/intents.jsonl` tem 102 frases rotuladas a mao, cobrindo os 10 rotulos e variacoes
informais. `scripts/eval_intents.py` mede a acuracia de regras, LLM e hibrido, imprime a
matriz de confusao, a acuracia por rotulo e as frases que erraram.

```
Regras (0 ms, sem rede)
  acuracia:   91.2%  (93/102)
  cobertura:  87.3%  (abstencoes: 13)
```

Nove dos dez rotulos ficam em 100%. O unico que as regras nao cobrem e `off_topic`: elas
se abstem de proposito, e e esse resto que justifica o LLM na arquitetura hibrida.

Sem `--llm` o script nao faz nenhuma chamada externa, entao roda no CI, que trava a
acuracia em 90%. A primeira execucao encontrou quatro bugs reais de classificacao — o
mais grave deles, "boa tarde" sendo interpretado como aceitar a oferta pendente.

---

## Contato e Suporte

Para duvidas sobre o projeto, consulte a documentacao ou entre em contato com o desenvolvedor.
