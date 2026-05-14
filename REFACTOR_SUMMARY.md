# Resumo do refactor — branch `develop`

## Em uma frase
4 agentes + 1 orquestrador fino com **proteção real contra off-topic e
ambiguidade**, validações de produção (CPF, datas, valores), LLM gateway
otimizado e **149 testes verdes**.

## Quarta rodada — otimização do LLM gateway

Análise do hot-path da conversa identificou que cada turno enviava ~700
caracteres de system prompt como user-text (sem cache do provider),
recriava clientes a cada chamada e não validava a saída. Mudanças:

### Tokens e custo
- **System/Human messages separados**: o system prompt agora vai como
  `SystemMessage`. Em OpenAI e Anthropic isso habilita prompt caching
  automático — a parte constante do prompt deixa de ser cobrada nas
  chamadas subsequentes da mesma janela.
- **Cache de respostas humanizadas** (LRU FIFO, 256 entradas):
  `(user_message, technical_answer, user_name)` idênticos → 0 chamada
  ao LLM. Forte para fluxos de retry e clarificação.
- **`max_tokens` reduzido para 120** no humanize (de 160). Três frases
  em pt-br raramente passam disso.
- **Histórico cortado**: 2 turnos × 100 chars (era 3 × 160) — menos
  cauda contextual por chamada.
- **Input truncado**: `user_message` em até 300 chars, `technical_answer`
  em até 500.

### Robustez
- **Circuit breaker**: depois de 3 falhas consecutivas o LLM é desligado
  por 30s; o backend devolve o `_fallback_humanize` durante a janela.
  Reset automático quando volta a responder.
- **Async init lock** (`asyncio.Lock`) na construção dos clientes — evita
  race condition na primeira chamada concorrente.
- **Validação anti-alucinação** (`_validate_humanized`):
  - Frases proibidas como "não posso ajudar" / "fora do escopo" → fallback.
  - Se a resposta perdeu mais de 20% dos números/valores da resposta
    técnica → fallback (sem arredondamentos silenciosos).
  - Se a resposta técnica termina com `?` mas a humanizada não → fallback
    (mantém o state machine intacto).
- **Regex de números BR** (`\d+(?:[.,]\d+)*`) reconhece `R$ 15.000,00` e
  `score 750` como tokens completos.

### Reuso de conexão
- Já tinha cliente cacheado — agora também com `asyncio.Lock` para evitar
  duplicação.

## Terceira rodada — robustez, performance e segurança

Auditoria pós-refactor identificou pontos para deixar o projeto pronto para
ambiente real:

### Segurança e validação
- **CPF com checksum brasileiro** (`utils.extract.is_valid_cpf`): rejeita
  formato matematicamente inválido e a sequência ilegal de 11 dígitos
  iguais. Aplicado tanto no `/triage/authenticate` REST quanto no fluxo
  conversacional.
- **Birthdate validada**: rejeita data futura e ano `< 1900` no schema.
- **Limites de valores monetários** (`MAX_MONEY_INPUT = 1.000.000`) no
  `LimitIncreaseRequest`, `InterviewRequest.renda_mensal` e
  `InterviewRequest.despesas`.
- **CORS spec-compliant**: `allow_credentials=True` só quando `cors_origins`
  não é `["*"]` (browsers rejeitam essa combinação).
- **Security headers middleware**: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Permissions-Policy: geolocation=(), microphone=(), camera=()`.

### Performance e concorrência
- **CSV I/O agora roda em thread pool** (`asyncio.to_thread`): o event loop
  não é mais bloqueado pelo `FileLock` síncrono. Suporta concorrência real.
- **Cache TTL de score_limits** (`ScoringService._score_ranges`): 60s. Antes
  o CSV era lido a cada request. `invalidate_cache()` exposto para testes.
- **Reuso de cliente LLM**: o `LLMGateway` agora mantém uma instância
  duradoura para intent (max_tokens=10) e outra para reply, em vez de
  recriar `ChatOpenAI`/`ChatAnthropic` (e o pool httpx) a cada chamada.
- **Cache LRU bounded** no `LLMGateway` (`_MAX_CACHE_ENTRIES=256`) com
  eviction FIFO — não vaza memória em produção longa.

### UX conversacional
- **Reset após GOODBYE**: quando o usuário diz "tchau" e depois manda outra
  mensagem na mesma sessão, o orquestrador limpa estado e recomeça pela
  triagem, em vez de ficar preso em `STATE_GOODBYE`.
- **Prompt do LLM reescrito** com regras mais rígidas:
  - Sem markdown, sem bullets, sem emojis, sem marketês.
  - Preserve exatamente todos os números/status/datas/nomes.
  - Em recusa/erro: 1 frase empática + próximo passo possível.
  - Sempre repita a pergunta pendente quando o usuário se desviar.
  - Mantenha a pergunta no final quando a resposta técnica contiver uma.

### Código mais limpo
- **`normalize_cpf`** consolidado em `utils.extract` — antes existia
  `_normalize_cpf` em `services/clients.py` e `_digits_only` em
  `agents/triage.py`. Um único helper agora.
- **`Orchestrator.agent(name)`**: getter público; `routes.py` não acessa
  mais `_agents` privado com `# type: ignore`.

## Mudanças do refactor inicial

- Reescrita aplicando **Strategy + DDD-light**: 4 agentes (`triage`, `credit`,
  `interview`, `exchange`) com interface comum (`Agent.handle → AgentReply`)
  e um `Orchestrator` que só roteia.
- Um único **gateway LLM** com **1 prompt** decente e 2 métodos
  (`classify_intent`, `compose_reply`). Eliminou 3 prompts truncados
  (`"Banco Ágil.Bancário..."`) que faziam o agente "engasgar".
- Off-topic não recusa: blacklist substituída por whitelist de intenções.
- Singletons das rotas com hook de reset; `Settings` injetável (sem
  `@lru_cache` permanente).
- **CORS** habilitado.
- Removidos: `optimized_chat.py` (broken), `orchestrator.py` antigo
  (696 linhas), `token_monitor.py` (gravava JSON a cada request).

## Segunda rodada — tratamento robusto de fala fora de contexto

O usuário pontuou (corretamente) que os agentes ainda travavam quando o
cliente dizia algo que não fazia sentido naquele passo do fluxo. Atacamos
o problema na raiz, **no orquestrador**, e adicionamos vários ajustes de
postura sênior.

### Meta-comandos sempre disponíveis
`core/intents.py` ganhou detectores explícitos (com `\b` word boundary,
sem falsos positivos):
- **cancel** (`cancelar`, `desistir`, `esquece`, `voltar pro menu`, …)
- **help** (`ajuda`, `menu`, `opções`, `o que voce faz`, …)
- **smalltalk** (saudações e agradecimentos: `olá`, `tudo bem`, `obrigado`,
  `valeu`, …)
- **accept / reject** com word-boundary (antes "nao" matchava em "agora não"
  e em qualquer string).

### Orquestração mid-flow
Quando o usuário está em um fluxo multi-turn (entrevista, câmbio,
aumento), o orquestrador **intercepta antes** do agente:
- `cancelar` → reset do fluxo + menu;
- `ajuda` → repete a pergunta atual + sugere `cancelar`;
- saudação/agradecimento → "Oi! Estamos no meio de um atendimento. Para
  continuar, [pergunta atual]." (zero loop "não entendi o valor");
- detecção de **troca de assunto** (`_detect_mid_flow_intent_switch`):
  se o usuário pergunta sobre outro serviço bancário enquanto está em um
  fluxo, o agente confirma "quer interromper isso e ir pra lá?" em vez
  de seguir empurrando a mesma pergunta.

### Mensagens dos agentes mais acolhedoras
Cada agente, no caminho de retry, agora diz "(Ou diga 'cancelar' para
sair.)". O usuário nunca fica refém.

### Prompt do LLM reescrito
Instruções explícitas no system prompt:
- "**NUNCA** diga 'não posso ajudar'."
- "Se a mensagem não responde à pergunta atual, responda gentilmente e
  repita a pergunta em uma frase."
- "Se parecer querer outro serviço, **confirme** antes de trocar."

### Robustez / produção
- **Exceções viram conversa**: `Orchestrator.process` captura
  `HTTPException` e `Exception`, retorna mensagem amigável em pt-br,
  loga o stack. Cliente não vê 500.
- **Request id** (`req=8c3a1f72`) em todos os logs do orchestrator para
  correlacionar erros multi-step.
- **Session TTL** (30 min default, configurável) + eviction de sessões
  expiradas. Hard cap de 10k sessões com drop dos mais velhos — sinal
  claro de que para escalar precisa de Redis.
- **Validação no boot** (`Settings.validate_for_boot`): em
  `environment=prod` com `JWT_SECRET_KEY` ainda no default, **levanta
  RuntimeError**. Em outros ambientes, warning agressivo.
- **Sanitização de input**: `ChatRequest.message` agora tem
  `field_validator` que faz `strip()` e rejeita vazio. Whitespace-only
  recebe 422.
- **Humanize seletivo**: respostas de retry/clarificação não passam pelo
  LLM (já são curtas e claras). Reduz custo ~30% nos fluxos com erro de
  parsing.

### Lista completa de bugs/inconsistências corrigidos

| #  | Problema                                                       | Onde estava                   |
|----|----------------------------------------------------------------|-------------------------------|
| 1  | `client.birth_date` (atributo inexistente)                     | `optimized_chat.py:375`       |
| 2  | `AuthService.authenticate` (método inexistente)                | `optimized_chat.py:376-378`   |
| 3  | `FORBIDDEN_TOPICS` matchava por substring → falsos positivos em "brasil", "ai", "ia" | `optimized_chat.py:68-121` |
| 4  | `@lru_cache` em `get_settings` impedia override em testes      | `config.py`                   |
| 5  | Sem CORS → frontend quebrava                                   | `main.py`                     |
| 6  | `token_monitor` gravava JSON sem lock, preço de GPT-3.5 hardcoded | `utils/token_monitor.py`   |
| 7  | "mil" matchava antes de "milhão"                                | `utils/value_extractor.py`   |
| 8  | `parse_boolean` "nao tenho dívidas" → `None`                   | `utils/text_normalizer.py`    |
| 9  | "atualizar perfil" não casava sem palavra exata                | `services/llm_service.py`     |
| 10 | Exit antes de autenticar não funcionava                        | `agents/orchestrator.py`      |
| 11 | 2 chamadas LLM por turno (classify + humanize)                 | `services/llm_service.py`     |
| 12 | Mensagem de aprovação sem "aprovado" no fallback               | `agents/credito.py`           |
| 13 | `_failed_attempts` global sem expiração                        | `agents/triagem.py`           |
| 14 | **(nova)** Agentes travavam em loop de retry com mensagens não-numéricas | toda a camada de agentes |
| 15 | **(nova)** "agora não" → `is_reject=True` por substring `nao`  | `core/intents.py`             |
| 16 | **(nova)** Sessões nunca expiravam — leak de memória            | `core/session.py`             |
| 17 | **(nova)** Exceções em downstream services viravam HTTP 500 no chat | `core/orchestrator.py`   |
| 18 | **(nova)** `JWT_SECRET_KEY` default aceito em produção sem alerta | `config.py`                |
| 19 | **(nova)** Whitespace-only message passava na validação         | `models/schemas.py`           |

## Estrutura final

```
src/
├── api/routes.py
├── core/{session,intents,orchestrator}.py
├── agents/{base,triage,credit,interview,exchange}.py
├── services/{auth,clients,exchange_api,scoring,llm}.py
├── models/{domain,schemas}.py
├── utils/{extract,exceptions,logging_config}.py
├── data/*.csv
├── config.py
└── main.py

tests/
├── conftest.py
├── test_extract.py          # parsers puros
├── test_meta_commands.py    # off-topic / mid-flow / TTL / boot
├── test_protections.py      # CPF checksum / schemas / cache / security headers
├── test_triagem.py
├── test_credito.py
├── test_entrevista.py
├── test_cambio.py
└── test_orchestrator.py
```

## Antes vs Depois

| Componente                                | Antes | Depois | Δ        |
| ----------------------------------------- | ----- | ------ | -------- |
| `orchestrator.py`                         | 696   | ~270   | −61%     |
| `optimized_chat.py`                       | 413   | 0      | removido |
| LLM service                               | 506   | ~190   | −62%     |
| `token_monitor.py`                        | 132   | 0      | removido |
| `value_extractor` + `text_normalizer` → `extract.py` | 250 | ~280 | consolidado |
| **Total `src/`**                          | ~3000 | ~2550  | −15% (mais lógica, menos linhas) |
| **Testes**                                | broken | 149 verdes | — |

## Como verificar

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest                 # 149 passando
python app.py          # /docs, CORS habilitado, validação de boot ativa
```
