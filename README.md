# Banco Ágil - API do Assistente Bancário

Back-end (FastAPI) do assistente virtual do Banco Ágil: um orquestrador de conversa que
autentica o cliente, consulta e solicita aumento de limite, cota moedas e conduz uma
entrevista financeira para atualizar o score.

- Front-end (Next.js): repositório `IA-Agent-Tech-For-Humans-Front-end`
- Guia rápido para avaliadores: [README-RECRUTADOR.md](README-RECRUTADOR.md)
- Arquitetura da conversa (regras + LLM): [docs/arquitetura-hibrida-v2.md](docs/arquitetura-hibrida-v2.md)
- Documentação técnica completa: [docs/DOCUMENTACAO-TECNICA.md](docs/DOCUMENTACAO-TECNICA.md)

## Funcionalidades

- Autenticação por CPF e data de nascimento (3 tentativas, bloqueio com expiração)
- Consulta de limite de crédito
- Solicitação de aumento de limite (com oferta de entrevista quando negada)
- Cotação de moedas (API externa com cache e taxas de contingência)
- Entrevista para atualização de score
- Conversa em linguagem natural: intenção antes do login, valores na própria frase,
  saída de fluxos com "cancelar", aviso de sessão expirada, tolerância a erros

## Requisitos

- Python 3.11+
- pip

## Instalação

```bash
git clone <url-do-repositorio>
cd IA-Agent-Tech-For-Humans-Back-end

python -m venv venv
.\venv\Scripts\activate        # Windows
# source venv/bin/activate     # Linux/Mac

pip install -r requirements-dev.txt   # runtime + pytest
cp .env.example .env                  # os valores padrão funcionam sem LLM
```

## Executando

```bash
python app.py            # http://localhost:8000  (Swagger em /docs)
```

No Windows, `start_system.bat` faz o mesmo ativando o venv.

### Docker

```bash
docker build -t agente-bancario .
docker run -p 8000:8000 --env-file .env agente-bancario
# ou: docker-compose up -d
```

## Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/health` | Status, versão e se o LLM está ativo |
| `POST` | `/api/unified/init` | Abre uma sessão de chat (mensagem de boas-vindas) |
| `POST` | `/api/unified/chat` | Envia uma mensagem para o orquestrador |
| `POST` | `/api/triage/authenticate` | Autenticação direta (retorna JWT) |
| `GET` | `/api/credit/limit` | Consulta limite (JWT) |
| `POST` | `/api/credit/request_increase` | Solicita aumento (JWT) |
| `POST` | `/api/interview/submit` | Envia entrevista financeira (JWT) |
| `GET` | `/api/exchange?from=USD&to=BRL` | Cotação (JWT) |

O front-end usa apenas `/unified/*`; os demais endpoints expõem os agentes individualmente.

Resposta do chat unificado:

```json
{
  "session_id": "…",
  "message": "texto para o cliente",
  "state": "authenticated | collecting_cpf | credit_increase_flow | interview_income | …",
  "authenticated": true,
  "token": "jwt ou null",
  "current_agent": "triage | credit | interview | exchange",
  "available_actions": ["consultar_limite", "solicitar_aumento", "cotacao_cambio", "atualizar_perfil"],
  "redirect_suggestion": { "should_redirect": true, "target_agent": "credit_increase" }
}
```

`available_actions` inclui `cancelar` enquanto um fluxo de coleta está aberto, e
`redirect_suggestion` indica que a última mensagem é uma pergunta de sim/não.

## Dados de Teste

| CPF         | Nome                      | Data Nascimento | Score |
| ----------- | ------------------------- | --------------- | ----- |
| 52998224725 | Maria Helena Santos       | 15/05/1990      | 315   |
| 71893456209 | João Pedro Oliveira       | 22/03/1985      | 620   |
| 89156734502 | Ana Carolina Lima         | 08/11/1992      | 609   |
| 34567891234 | Carlos Eduardo Souza      | 30/07/1978      | 450   |
| 89123456789 | Patricia Souza Nascimento | 14/06/1976      | 920   |

Lista completa em `src/data/clientes.csv`. Os testes automatizados usam uma base própria e
isolada (veja `tests/conftest.py`).

## Testes

```bash
pytest                          # suíte completa (sem chamadas de LLM)
pytest --cov=src --cov-report=html
pytest tests/test_conversation_ux.py -v
```

## Variáveis de Ambiente

| Variável                 | Descrição                                        | Padrão                                     |
| ------------------------ | ------------------------------------------------ | ------------------------------------------ |
| `JWT_SECRET_KEY`         | Chave secreta para JWT (avisa no log se for a padrão) | dev-secret-key...                     |
| `JWT_EXPIRATION_MINUTES` | Expiração do token                               | 15                                         |
| `USE_LANGCHAIN`          | Ativa classificação/humanização via LLM          | false                                      |
| `LLM_PROVIDER`           | `openai` ou `anthropic`                          | openai                                     |
| `OPENAI_API_KEY`         | Chave OpenAI                                     | -                                          |
| `ANTHROPIC_API_KEY`      | Chave Anthropic                                  | -                                          |
| `EXCHANGE_API_URL`       | URL da API de câmbio                             | https://api.exchangerate-api.com/v4/latest |
| `DATA_DIR`               | Diretório dos CSVs                               | src/data                                   |
| `LOG_LEVEL`              | Nível de log                                     | INFO                                       |
| `MAX_AUTH_ATTEMPTS`      | Tentativas de autenticação                       | 3                                          |
| `AUTH_LOCKOUT_MINUTES`   | Janela de bloqueio por CPF em `/triage`          | 15                                         |
| `SESSION_TTL_MINUTES`    | Inatividade até a sessão de chat expirar         | 30                                         |
| `MAX_MESSAGE_LENGTH`     | Tamanho máximo de mensagem processada            | 2000                                       |

## Estrutura do Projeto

```
├── app.py                       # Ponto de entrada (uvicorn)
├── requirements.txt             # Dependências de runtime
├── requirements-dev.txt         # + pytest
├── Dockerfile / docker-compose.yml / render.yaml
├── docs/                        # Arquitetura, documentação técnica, histórico
├── src/
│   ├── main.py                  # App FastAPI, lifespan, handler global de erros, /health
│   ├── config.py                # Settings (pydantic-settings)
│   ├── api/routes.py            # Endpoints; instancia e injeta agentes/serviços
│   ├── agents/
│   │   ├── orchestrator.py      # Máquina de estados da conversa
│   │   ├── triagem.py           # Autenticação com limite de tentativas
│   │   ├── credito.py           # Limite e aumento
│   │   ├── entrevista.py        # Entrevista financeira
│   │   └── cambio.py            # Cotações
│   ├── services/                # auth (JWT), csv, llm (regras + LangChain), score
│   ├── models/                  # Entidades e schemas Pydantic
│   ├── utils/                   # Normalização de texto, extratores, formatação, exceções
│   └── data/                    # clientes.csv, score_limite.csv, solicitacoes_aumento_limite.csv
└── tests/
```

## Decisões Técnicas

- **Regras primeiro, LLM depois**: palavras-chave resolvem a maioria das mensagens em 0 ms;
  o LLM só classifica frases ambíguas e reescreve o tom, nunca decide ações nem acessa dados.
- **Tudo funciona sem LLM**: com `USE_LANGCHAIN=false` o sistema usa regras e templates.
- **CSV com FileLock**: persistência simples e inspecionável, suficiente para o MVP.
- **JWT stateless** para os endpoints diretos; sessões de chat em memória com TTL.

## Licença

MIT License
