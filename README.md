# Agente Bancario Inteligente - Banco Agil

Sistema de atendimento ao cliente para o banco digital ficticio **Banco Agil**, utilizando agentes de IA especializados para autenticacao, consultas de credito, entrevistas financeiras e cotacao de moedas.

## Visao Geral

Este projeto implementa um sistema de atendimento bancario automatizado com 4 agentes especializados:

1. **Agente de Triagem**: Porta de entrada do sistema. Autentica clientes via CPF e data de nascimento, direcionando para o agente apropriado.

2. **Agente de Credito**: Consulta limites de credito e processa solicitacoes de aumento de limite baseado no score do cliente.

3. **Agente de Entrevista de Credito**: Conduz entrevistas financeiras para recalcular o score de credito do cliente.

4. **Agente de Cambio**: Realiza consultas de cotacao de moedas em tempo real.

## Arquitetura do Sistema

```
                    +-------------------+
                    |    Streamlit UI   |
                    |   (Chat Interface)|
                    +--------+----------+
                             |
                             v
+------------------------------------------------------------------+
|                        FastAPI Backend                            |
+------------------------------------------------------------------+
|                                                                    |
|  +------------------+  +------------------+  +------------------+  |
|  | Agente Triagem   |->| Agente Credito   |  | Agente Cambio    |  |
|  | - Autenticacao   |  | - Consulta Limite|  | - Cotacao Moedas |  |
|  | - Roteamento     |  | - Aumento Limite |  | - API Externa    |  |
|  +------------------+  +--------+---------+  +------------------+  |
|                               |                                    |
|                               v                                    |
|                    +------------------+                            |
|                    | Agente Entrevista|                            |
|                    | - Coleta Dados   |                            |
|                    | - Calcula Score  |                            |
|                    +------------------+                            |
|                                                                    |
+------------------------------------------------------------------+
                             |
              +--------------+---------------+
              |              |               |
              v              v               v
        +----------+  +-------------+  +------------------+
        |clientes. |  |score_limite.|  |solicitacoes_     |
        |csv       |  |csv          |  |aumento_limite.csv|
        +----------+  +-------------+  +------------------+
```

### Fluxo de Dados

1. **Autenticacao**: Usuario informa CPF e data de nascimento -> validacao contra `clientes.csv`
2. **Consulta de Credito**: Score do cliente -> `score_limite.csv` -> limite disponivel
3. **Aumento de Limite**: Solicitacao -> avaliacao com score -> registro em `solicitacoes_aumento_limite.csv`
4. **Entrevista**: Dados financeiros -> formula de score -> atualizacao em `clientes.csv`

## Funcionalidades Implementadas

### Agente de Triagem
- Saudacao inicial
- Coleta e validacao de CPF (11 digitos)
- Coleta e validacao de data de nascimento
- Autenticacao contra base de clientes (CSV)
- 3 tentativas de autenticacao
- Deteccao de intencao via LLM ou regras
- Redirecionamento automatico para agentes

### Agente de Credito
- Consulta de limite atual baseado no score
- Calculo de limite disponivel (80% do total)
- Solicitacao de aumento de limite
- Avaliacao automatica baseada em `score_limite.csv`
- Registro de solicitacoes com status (aprovado/rejeitado)
- Oferta de entrevista quando rejeitado

### Agente de Entrevista de Credito
- Coleta de renda mensal
- Tipo de emprego (formal, autonomo, desempregado)
- Despesas fixas mensais
- Numero de dependentes
- Dividas ativas
- Calculo de score conforme formula especificada
- Atualizacao do score no cadastro

**Formula de Score:**
```
score = (
    (renda_mensal / (despesas + 1)) * 30 +
    peso_emprego[tipo_emprego] +
    peso_dependentes[num_dependentes] +
    peso_dividas[tem_dividas]
)

Pesos:
- peso_emprego: formal=300, autonomo=200, desempregado=0
- peso_dependentes: 0=100, 1=80, 2=60, 3+=30
- peso_dividas: sim=-100, nao=100
```

### Agente de Cambio
- Consulta de cotacao em tempo real
- Suporte a USD, EUR, GBP e BRL
- Fallback para taxas mock quando API indisponivel

## Tutorial de Execucao

### Pre-requisitos
- Python 3.11+
- pip (gerenciador de pacotes)

### Instalacao

```bash
# 1. Clone o repositorio
git clone <url-do-repositorio>
cd IA-Agent-Tech-For-Humans-Back-end

# 2. Crie um ambiente virtual (recomendado)
python -m venv venv

# Windows
.\venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

# 3. Instale as dependencias
pip install -r requirements.txt

# 4. Configure o ambiente
cp .env.example .env
# Edite o .env se necessario (valores padrao funcionam)
```

### Executando a Interface (Streamlit)

```bash
# Execute a interface de chat
streamlit run src/ui/streamlit_app.py
```

A interface estara disponivel em: **http://localhost:8501**

### Executando a API (Backend)

```bash
# Execute o servidor FastAPI
python app.py
```

A API estara disponivel em: **http://localhost:8000**
Documentacao automatica: **http://localhost:8000/docs**

### Usando Docker

```bash
# Build da imagem
docker build -t agente-bancario .

# Executar container
docker run -p 8000:8000 agente-bancario
```

## Testando a Aplicacao

### Clientes de Teste

| CPF | Nome | Data Nascimento | Score |
|-----|------|-----------------|-------|
| 12345678901 | Maria Silva | 15/05/1990 | 750 |
| 98765432100 | Joao Santos | 22/03/1985 | 600 |
| 11122233344 | Ana Oliveira | 08/11/1992 | 850 |
| 55566677788 | Carlos Souza | 30/07/1978 | 450 |
| 99988877766 | Beatriz Lima | 12/01/1995 | 300 |

### Exemplo de Uso na Interface

1. Acesse http://localhost:8501
2. Digite o CPF: `12345678901`
3. Digite a data de nascimento: `15/05/1990`
4. Apos autenticacao, escolha uma opcao:
   - `1` - Consultar limite de credito
   - `2` - Solicitar aumento de limite
   - `3` - Consultar cotacao de moedas
   - `4` - Encerrar atendimento

### Executando Testes Automatizados

```bash
# Rodar todos os testes
pytest

# Com cobertura de codigo
pytest --cov=src --cov-report=html

# Testes especificos
pytest tests/test_triagem.py -v
pytest tests/test_credito.py -v
pytest tests/test_entrevista.py -v
pytest tests/test_cambio.py -v
```

## Desafios Enfrentados e Solucoes

### 1. Sincronia entre Streamlit e AsyncIO
**Desafio**: Streamlit e preciso chamar funcoes async do backend.
**Solucao**: Uso de `asyncio.run()` para executar coroutines no contexto sincrono do Streamlit.

### 2. Persistencia Thread-Safe em CSV
**Desafio**: Multiplas requisicoes podem modificar CSVs simultaneamente.
**Solucao**: Implementacao de `FileLock` para garantir acesso exclusivo aos arquivos.

### 3. Deteccao de Intencao sem LLM
**Desafio**: Sistema precisa funcionar mesmo sem API de LLM.
**Solucao**: Fallback para classificacao baseada em keywords quando LLM indisponivel.

### 4. Validacao de Dados de Entrada
**Desafio**: CPF pode vir com ou sem formatacao.
**Solucao**: Normalizacao automatica removendo pontos e tracos.

### 5. Transicao Suave entre Agentes
**Desafio**: Usuario nao deve perceber troca de agentes.
**Solucao**: Maquina de estados no Streamlit com transicoes implicitas.

## Escolhas Tecnicas e Justificativas

### FastAPI
- Framework moderno e rapido para APIs Python
- Suporte nativo a async/await
- Documentacao automatica via OpenAPI
- Validacao de dados com Pydantic

### Streamlit
- Simplicidade para criar interfaces de chat
- Gerenciamento de estado de sessao
- Atualizacao reativa da interface

### CSV para Persistencia
- Simplicidade para MVP
- Facilidade de inspecao e debug
- Atende requisitos do desafio (clientes.csv, score_limite.csv)

### JWT para Autenticacao
- Padrao da industria
- Stateless (nao requer sessao no servidor)
- Expiracao configuravel

### LangChain (Opcional)
- Facilita integracao com diferentes LLMs
- Fallback para regras quando indisponivel
- Configuravel via variavel de ambiente

## Estrutura do Projeto

```
IA-Agent-Tech-For-Humans-Back-end/
├── app.py                          # Ponto de entrada da API
├── requirements.txt                # Dependencias Python
├── pyproject.toml                  # Configuracao do projeto
├── Dockerfile                      # Container Docker
├── .env.example                    # Template de variaveis de ambiente
├── src/
│   ├── main.py                     # Configuracao FastAPI
│   ├── config.py                   # Gerenciamento de configuracoes
│   ├── api/
│   │   └── routes.py               # Endpoints da API
│   ├── agents/
│   │   ├── triagem.py              # Agente de Triagem
│   │   ├── credito.py              # Agente de Credito
│   │   ├── entrevista.py           # Agente de Entrevista
│   │   └── cambio.py               # Agente de Cambio
│   ├── services/
│   │   ├── auth_service.py         # Servico de autenticacao JWT
│   │   ├── csv_service.py          # Persistencia em CSV
│   │   ├── llm_service.py          # Integracao com LLM
│   │   └── score_service.py        # Calculo de score
│   ├── models/
│   │   ├── domain.py               # Modelos de dominio
│   │   └── schemas.py              # Schemas Pydantic
│   ├── utils/
│   │   ├── exceptions.py           # Excecoes customizadas
│   │   └── logging_config.py       # Configuracao de logs
│   ├── ui/
│   │   └── streamlit_app.py        # Interface Streamlit
│   └── data/
│       ├── clientes.csv            # Base de clientes
│       ├── score_limite.csv        # Tabela score x limite
│       └── solicitacoes_aumento_limite.csv  # Solicitacoes registradas
└── tests/
    ├── conftest.py                 # Fixtures de teste
    ├── test_triagem.py             # Testes do agente de triagem
    ├── test_credito.py             # Testes do agente de credito
    ├── test_entrevista.py          # Testes do agente de entrevista
    └── test_cambio.py              # Testes do agente de cambio
```

## Variaveis de Ambiente

| Variavel | Descricao | Padrao |
|----------|-----------|--------|
| `JWT_SECRET_KEY` | Chave secreta para JWT | dev-secret-key... |
| `JWT_EXPIRATION_MINUTES` | Tempo de expiracao do token | 15 |
| `USE_LANGCHAIN` | Ativar deteccao de intencao via LLM | false |
| `LLM_PROVIDER` | Provedor LLM (openai/anthropic) | openai |
| `OPENAI_API_KEY` | Chave API OpenAI | - |
| `ANTHROPIC_API_KEY` | Chave API Anthropic | - |
| `EXCHANGE_API_URL` | URL da API de cambio | https://api.exchangerate-api.com/v4/latest |
| `DATA_DIR` | Diretorio dos arquivos CSV | src/data |
| `LOG_LEVEL` | Nivel de log | INFO |

## Licenca

MIT License
