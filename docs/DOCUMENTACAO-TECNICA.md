# Documentacao Tecnica - Agente Bancario Inteligente

## Visao Geral

O **Agente Bancario Inteligente** é um sistema de atendimento digital que utiliza Inteligencia Artificial para simular um atendente bancario virtual. O sistema oferece servicos como autenticacao, consulta de limite de credito, solicitacao de aumento, cotacao de moedas e entrevista financeira para atualizacao de score.

---

## Arquitetura do Sistema

```
┌─────────────────────────────────────────────────────────────────┐
│                         Cliente (Frontend)                        │
│                    Streamlit / API Consumer                       │
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
│    AuthService │ CSVService │ ScoreService │ LLMService          │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Data Layer                                 │
│        clientes.csv │ score_limite.csv │ solicitacoes.csv        │
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

### Executando o Frontend (Streamlit)

```bash
streamlit run src/ui/streamlit_app.py
```

Interface disponivel em: `http://localhost:8501`

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
3. Busca cliente no arquivo `clientes.csv`
4. Valida data de nascimento
5. Gera token JWT em caso de sucesso
6. Controla tentativas (maximo 3)

**Deteccao de Intencao**:
- Usa LLM (se configurado) ou regras baseadas em keywords
- Classifica em: `credit_limit`, `request_increase`, `exchange_rate`, `interview`, `other`

#### 2. Agente de Credito (credito.py)

**Responsabilidade**: Consulta e aumento de limite

**Funcionamento - Consulta**:
1. Recebe CPF do token JWT
2. Busca score do cliente
3. Consulta tabela `score_limite.csv` para determinar limite
4. Retorna limite atual e disponivel (80% do total)

**Funcionamento - Aumento**:
1. Recebe valor solicitado
2. Compara com limite maximo para o score atual
3. Aprova se solicitado <= maximo permitido
4. Nega se solicitado > maximo permitido
5. Registra solicitacao em `solicitacoes_aumento_limite.csv`
6. Se negado, oferece entrevista para melhorar score

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
| `GET` | `/health` | Health check do servidor |
| `POST` | `/chat/init` | Inicializa sessao de chat |
| `POST` | `/chat` | Envia mensagem para o chat |
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
  "cpf": "12345678901",
  "current_limit": 15000.0,
  "available_limit": 12000.0,
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
  "cpf": "12345678901",
  "requested_limit": 20000.0,
  "status": "approved",
  "message": "Seu pedido de aumento foi aprovado!",
  "offer_interview": false
}
```

**Response (negado)**:
```json
{
  "cpf": "12345678901",
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

- Classificacao baseada em keywords
- Sem dependencias externas
- Mais rapido e confiavel
- Ideal para ambientes sem acesso a API

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

### Arquivos CSV

| Arquivo | Descricao | Campos |
|---------|-----------|--------|
| `clientes.csv` | Base de clientes | cpf, nome, data_nascimento, score, limite_atual |
| `score_limite.csv` | Tabela score x limite | score_min, score_max, limite |
| `solicitacoes_aumento_limite.csv` | Log de solicitacoes | cpf, data_hora, limite_atual, novo_limite, status |

### Thread Safety

Operacoes de escrita em CSV usam `FileLock` para garantir acesso exclusivo:

```python
from filelock import FileLock

lock = FileLock(f"{filepath}.lock", timeout=10)
with lock:
    # operacao segura no arquivo
```

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
| `LLM_MODEL` | Modelo a usar | gpt-4o-mini |
| `OPENAI_API_KEY` | Chave API OpenAI | - |
| `ANTHROPIC_API_KEY` | Chave API Anthropic | - |
| `EXCHANGE_API_URL` | URL API de cambio | api.exchangerate-api.com |
| `DATA_DIR` | Diretorio dos CSVs | src/data |
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

| CPF | Nome | Data Nascimento | Score | Limite |
|-----|------|-----------------|-------|--------|
| 12345678901 | Maria Silva | 15/05/1990 | 750 | R$ 15.000 |
| 98765432100 | Joao Santos | 22/03/1985 | 600 | R$ 8.000 |
| 11122233344 | Ana Oliveira | 08/11/1992 | 850 | R$ 25.000 |
| 55566677788 | Carlos Souza | 30/07/1978 | 450 | R$ 2.500 |
| 99988877766 | Beatriz Lima | 12/01/1995 | 300 | R$ 1.000 |

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
│   ├── architecture.md      # Arquitetura do sistema
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
│   │   ├── cambio.py        # Agente cambio
│   │   └── optimized_chat.py # Chat otimizado
│   │
│   ├── services/
│   │   ├── auth_service.py  # JWT
│   │   ├── csv_service.py   # Persistencia
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
│   │   ├── text_normalizer.py # Normalizacao
│   │   ├── token_monitor.py # Monitor tokens
│   │   └── value_extractor.py # Extratores
│   │
│   └── data/
│       ├── clientes.csv
│       ├── score_limite.csv
│       └── solicitacoes_aumento_limite.csv
│
└── tests/
    ├── conftest.py          # Fixtures
    ├── test_triagem.py
    ├── test_credito.py
    ├── test_entrevista.py
    ├── test_cambio.py
    ├── test_orchestrator.py
    ├── test_integration.py
    └── test_restrictions.py
```

---

## Contato e Suporte

Para duvidas sobre o projeto, consulte a documentacao ou entre em contato com o desenvolvedor.
