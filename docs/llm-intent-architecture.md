# Classificacao de Intencao: Regras + LLM

## Visao Geral

A classificacao de intencao (`LLMService.classify_intent`) e hibrida: **regras por palavra
inteira** respondem primeiro (0 ms, sem custo) e o **LLM** entra apenas quando as regras nao
tem resposta. Isso substitui o esquema anterior, em que o LLM era consultado primeiro para
tudo e as regras eram apenas fallback por substring.

## Motivacao

### Problemas anteriores
- Keywords por substring: "um" casava em "aumentar", "ha" em "tchau", "no" em "novo", "ia" em "dia"
- Nao existiam os intents `greeting`, `goodbye`, `confirm`, `reject`, `off_topic`; "sim"/"nao" eram
  tratados por listas separadas no orquestrador, tambem por substring
- Frases como "acho que nao precisa" nao eram reconhecidas como encerramento
- Cliente `ChatOpenAI` recriado a cada chamada e timeout de 8 s

### Resultado
- Regras resolvem a maioria das mensagens instantaneamente
- LLM cobre as frases sem palavra-chave, com timeout de 2,5 s e fallback
- Uma unica funcao (`classify_intent`) e usada pelo orquestrador e pelo agente de triagem

## Intents Suportados

| Intent | Descricao | Exemplos |
|--------|-----------|----------|
| `greeting` | Saudacao | "oi", "bom dia", "tudo bem" |
| `goodbye` | Encerrar conversa | "tchau", "era so isso", "pode encerrar" |
| `confirm` | Aceitar oferta | "sim", "pode ser", "vamos la", "beleza" |
| `reject` | Recusar oferta / cancelar | "nao", "depois", "agora nao", "cancelar" |
| `credit_limit` | Consultar limite/score | "qual meu limite", "quanto tenho disponivel" |
| `request_increase` | Solicitar aumento | "quero aumentar meu limite" |
| `exchange_rate` | Cotacao de moedas | "cotacao do dolar", "euro em reais", "USD" |
| `interview` | Atualizar perfil | "atualizar meus dados", "melhorar meu score" |
| `off_topic` | Assunto nao bancario (so via LLM) | "quem descobriu o brasil" |
| `other` | Nao classificado (LLM) | - |

`classify_intent` retorna `None` quando nem regras nem LLM classificam; o orquestrador mostra o menu.

## Fluxo

```
mensagem
   |
   v
classify_with_rules()                          0 ms
   |  palavras-chave por intent bancario (palavra inteira, frases pesam 2)
   |  credit_limit + request_increase juntos -> request_increase
   |  um so intent com pontos -> retorna
   |  empate entre intents -> None (ambiguo)
   |  depois: goodbye -> reject/confirm -> greeting
   |
   |-- achou? -> retorna
   |
   v
LLM (apenas se allow_llm e USE_LANGCHAIN com chave)     ate 2,5 s
   |  cache LRU por mensagem normalizada (INTENT_CACHE_MAX_SIZE)
   |  prompt de sistema com os rotulos; max_tokens=8; temperature=0
   |  timeout -> None
   v
None
```

### Onde o LLM nao e consultado
- Dentro de fluxos de coleta (renda, valor, moeda, sim/nao): o dado e extraido por parser; se
  falhar, apenas regras decidem se o usuario quer sair ("cancelar", "tchau", outra intencao)
- Antes da autenticacao, quando a mensagem contem digitos (provavel CPF/data digitado errado)

## Prompt de Classificacao

```
[system]
Voce classifica a intencao de mensagens de clientes de um chatbot bancario (Banco Agil).
Responda apenas com um destes rotulos, sem explicacao:
credit_limit: consultar limite, saldo ou score
request_increase: pedir aumento de limite
exchange_rate: cotacao, cambio ou moedas
interview: atualizar perfil ou dados financeiros
greeting: saudacao
goodbye: encerrar a conversa, despedida, "era so isso"
confirm: aceitar uma oferta (sim, pode, quero)
reject: recusar uma oferta (nao, depois, agora nao)
off_topic: assunto nao bancario
other: nao classificavel

[human]
Mensagem: "{message}"
```

## Humanizacao

`humanize_response` reescreve mensagens tecnicas (autenticacao, saudacoes, recusas, despedidas)
com um prompt de sistema que exige: manter todos os dados e perguntas, nao inventar nada,
1 a 3 frases, sem markdown, chamar o cliente pelo primeiro nome. Timeout de 4 s; em falha,
templates em portugues cobrem os casos comuns (CPF invalido/nao encontrado, data incorreta).

Mensagens com numeros (limite, cotacao, score) **nao** passam pelo LLM.

## Configuracoes

| Variavel | Padrao | Descricao |
|----------|--------|-----------|
| `USE_LANGCHAIN` | `false` | Liga o LLM (precisa de chave do provedor) |
| `LLM_PROVIDER` | `openai` | `openai` ou `anthropic` |
| `LLM_MODEL` | `gpt-4o-mini` | Modelo OpenAI |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Modelo Anthropic |
| `LLM_INTENT_TIMEOUT_SECONDS` | `2.5` | Timeout da classificacao |
| `LLM_HUMANIZE_TIMEOUT_SECONDS` | `4.0` | Timeout da humanizacao |
| `INTENT_CACHE_MAX_SIZE` | `500` | Entradas no cache LRU de intencoes |

## O Que Permanece Rule-Based

| Funcao | Arquivo | Motivo |
|--------|---------|--------|
| `extract_monetary_value()` | value_extractor.py | Regex e mais preciso para numeros |
| `extract_currency_codes()` | value_extractor.py | Codigos ISO finitos; preserva a ordem ("dolar para real") |
| `extract_employment_type()` | value_extractor.py | Vocabulario fechado |
| `parse_boolean_response()` | text_normalizer.py | Sim/nao com negacao prevalecendo |
| `parse_date_from_text()` | text_normalizer.py | Formatos estruturados |
| `extract_cpf_from_text()` | text_normalizer.py | 11 digitos |

Todas usam `contains_word()` (palavra inteira) em vez de substring.

## Custos Estimados

| Metrica | Valor |
|---------|-------|
| Modelo | gpt-4o-mini |
| Custo por classificacao via LLM | ~$0.00001 |
| Fracao de mensagens que chegam ao LLM | minoria (regras resolvem o restante) |
| Humanizacao (max 160 tokens de saida) | ~$0.0001 por mensagem humanizada |

## Testes

- `tests/test_intent_rules.py`: tabela de frases -> intent, prioridade bancaria sobre sim/nao,
  empate -> `None`, correcoes de fronteira de palavra
- `tests/test_conversation_ux.py`: cenarios de conversa ponta a ponta sem LLM
- `tests/test_natural_language.py`: extratores e parser
