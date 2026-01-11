# Architecture Overview

## System Design

The Agente Bancário Inteligente is designed as a modular FastAPI application following clean architecture principles.

```
┌─────────────────────────────────────────────────────────────┐
│                      API Layer (routes.py)                   │
├─────────────────────────────────────────────────────────────┤
│                      Agent Layer                             │
│  ┌─────────┐  ┌─────────┐  ┌───────────┐  ┌─────────┐      │
│  │ Triagem │  │ Credito │  │Entrevista │  │ Cambio  │      │
│  └────┬────┘  └────┬────┘  └─────┬─────┘  └────┬────┘      │
├───────┼────────────┼─────────────┼─────────────┼────────────┤
│                    Service Layer                             │
│  ┌─────────────┐ ┌─────────────┐ ┌──────────────┐          │
│  │ CSV Service │ │Score Service│ │ Auth Service │          │
│  └─────────────┘ └─────────────┘ └──────────────┘          │
│  ┌─────────────┐                                            │
│  │ LLM Service │                                            │
│  └─────────────┘                                            │
├─────────────────────────────────────────────────────────────┤
│                      Data Layer (CSV)                        │
│  clientes_sample.csv │ score_limite.csv │ solicitacoes.csv  │
└─────────────────────────────────────────────────────────────┘
```

## Components

### API Layer
- FastAPI routes handling HTTP requests
- Request validation via Pydantic schemas
- JWT authentication via Bearer tokens

### Agent Layer
- **TriageAgent**: Handles authentication and intent detection
- **CreditAgent**: Manages credit limit queries and increase requests
- **InterviewAgent**: Processes financial interviews and score updates
- **ExchangeAgent**: Fetches currency exchange rates

### Service Layer
- **CSVService**: Thread-safe CSV operations with filelock
- **ScoreService**: Score calculation and limit evaluation logic
- **AuthService**: JWT token creation and validation
- **LLMService**: Intent classification (LangChain or rule-based)

## LangChain Integration

LangChain is used exclusively for natural language intent classification:

```
User Message → LLMService → Intent Classification
                   ↓
        ┌─────────┴─────────┐
        │  USE_LANGCHAIN?   │
        └─────────┬─────────┘
                  │
        ┌─────────┴─────────┐
    YES │                   │ NO
        ↓                   ↓
┌───────────────┐   ┌───────────────┐
│  LLM Chain    │   │  Rule-based   │
│  (low temp)   │   │  (keywords)   │
└───────┬───────┘   └───────┬───────┘
        │                   │
        └─────────┬─────────┘
                  ↓
            Intent Result
```

### Why Limited LangChain Usage?

1. **Determinism**: Business logic requires predictable outcomes
2. **Reliability**: System works without external API dependencies
3. **Cost**: Minimizes API calls to LLM providers
4. **Testing**: Rule-based fallback enables reliable unit tests

## Data Flow

### Authentication Flow
```
POST /triage/authenticate
     │
     ↓
┌────────────┐     ┌─────────────┐
│  Validate  │ ──→ │   Lookup    │
│    CPF     │     │  in CSV     │
└────────────┘     └─────────────┘
     │                   │
     ↓                   ↓
┌────────────┐     ┌─────────────┐
│   Check    │ ←── │   Match     │
│ Birthdate  │     │   Found?    │
└────────────┘     └─────────────┘
     │
     ↓
┌────────────┐     ┌─────────────┐
│  Generate  │ ──→ │   Detect    │
│    JWT     │     │   Intent    │
└────────────┘     └─────────────┘
```

### Credit Limit Request Flow
```
POST /credit/request_increase
     │
     ↓
┌────────────┐     ┌─────────────┐
│  Validate  │ ──→ │   Get       │
│   Token    │     │   Score     │
└────────────┘     └─────────────┘
     │                   │
     ↓                   ↓
┌────────────┐     ┌─────────────┐
│  Evaluate  │ ←── │   Apply     │
│  Request   │     │   Rules     │
└────────────┘     └─────────────┘
     │
     ↓
┌────────────┐
│  Persist   │
│  to CSV    │
└────────────┘
```

## Security

- JWT tokens with 15-minute expiration
- CPF data partially masked in logs
- Rate limiting via attempt counter
- Input validation on all endpoints

## File Structure

```
agente-bancario-ia/
├── src/
│   ├── api/          # HTTP endpoints
│   ├── agents/       # Business logic orchestration
│   ├── services/     # Core services
│   ├── models/       # Data schemas
│   ├── utils/        # Utilities
│   └── data/         # CSV storage
└── tests/            # Test suite
```
