# Guia para Avaliadores - Banco Ágil

## Acesso Rápido (Produção)

Você pode testar o projeto diretamente sem precisar rodar localmente:

| Ambiente | URL |
|----------|-----|
| **Front-end (Interface)** | https://ia-agent-tech-for-humans-frontend.vercel.app/ |
| **Back-end (API)** | https://ia-agent-tech-for-humans-back-end.onrender.com |

> **Dica**: Acesse a URL do front-end para usar o chat e interagir com o agente bancário.

---

## Como Usar

### 1. Pegue um CPF da base de dados

Os dados dos clientes estão no arquivo `src/data/clientes.csv`. Use qualquer CPF desta lista:

| CPF | Nome | Data de Nascimento |
|-----|------|--------------------|
| 52998224725 | Maria Helena Santos | 15/05/1990 |
| 71893456209 | João Pedro Oliveira | 22/03/1985 |
| 89156734502 | Ana Carolina Lima | 08/11/1992 |
| 34567891234 | Carlos Eduardo Souza | 30/07/1978 |
| 45678912345 | Beatriz Ferreira Costa | 12/01/1995 |
| 67891234567 | Fernanda Rodrigues Silva | 18/04/1988 |
| 89123456789 | Patricia Souza Nascimento | 14/06/1976 |

### 2. Converse naturalmente

Você pode enviar mensagens da forma que quiser! O agente entende linguagem natural:

- "Quero ver meu limite"
- "Qual é a cotação do dólar?"
- "Quero aumentar meu limite de crédito"
- "Me ajuda com câmbio"

Não precisa seguir um formato específico - apenas converse normalmente.

---

## Informações Importantes

### Sobre o armazenamento de dados

Este projeto **não utiliza banco de dados tradicional**. Os dados são armazenados em arquivos CSV localizados em `src/data/`:

- `clientes.csv` - Cadastro de clientes
- `score_limite.csv` - Tabela de score x limite
- `solicitacoes_aumento_limite.csv` - Registro de solicitações

Essa escolha foi feita para simplificar o MVP e facilitar a inspeção dos dados durante a avaliação.

### Funcionalidades disponíveis

- Autenticação por CPF e data de nascimento
- Consulta de limite de crédito
- Solicitação de aumento de limite
- Cotação de moedas estrangeiras
- Entrevista para atualização de score

---

## URLs Locais (se preferir rodar localmente)

| Ambiente | URL |
|----------|-----|
| Front-end | http://localhost:3000 |
| Back-end | http://localhost:8000 |
| Documentação da API | http://localhost:8000/docs |

Para instruções de instalação local, consulte o `README.md` principal.
