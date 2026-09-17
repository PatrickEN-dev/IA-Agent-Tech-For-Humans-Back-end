# Arquitetura Hibrida V2 - Orchestrator

## Visao Geral

O orquestrador (`src/agents/orchestrator.py`) implementa uma arquitetura **hibrida**:

- **Camada deterministica**: autenticacao, validacoes, regras de negocio, coleta de dados
- **Camada de linguagem**: classificacao de intencao (regras primeiro, LLM como reforco) e humanizacao das respostas

A V2 nao e um arquivo novo. As ideias do rascunho `OrchestratorV2` (limite de tentativas,
nome do cliente na sessao, tratamento de erro por acao, `collecting_for` generico) foram
incorporadas ao orquestrador em producao, mantendo o contrato da API (`state`,
`current_agent`, `redirect_suggestion`) que o front-end e os testes ja usam.

## Por Que Hibrido?

### Problema do "tudo deterministico"
- Keywords por substring geravam falsos positivos ("um" dentro de "aumentar", "no" dentro de "novo")
- Usuario preso em fluxos: "nao consegui identificar o valor" sem saida
- Frases naturais de encerramento ("acho que nao precisa") nao eram reconhecidas

### Problema do "tudo LLM"
- Uma chamada de LLM por mensagem, inclusive para "15000" ou um CPF: lento e caro
- Imprevisivel e dificil de testar
- Risco de seguranca se o LLM decide acoes com dados do cliente

### Solucao
- Regras (0 ms) resolvem a maioria das mensagens; LLM entra so quando as regras nao tem resposta
- LLM decide **roteamento e tom**, o codigo executa **acoes**
- Autenticacao, calculo de score, aprovacao de limite e acesso a CSV sao 100% deterministicos
- Toda chamada de LLM tem timeout curto e fallback por regras/templates

## Pipeline de uma Mensagem

```
process_message()
   |
   |-- limpa sessoes ociosas (TTL 30 min) e registra a mensagem no historico
   |-- sessao travada (3 falhas de autenticacao)? -> resposta fixa
   |-- sessao em GOODBYE? -> reinicia a sessao
   |
   +-- COLLECTING_CPF / COLLECTING_BIRTHDATE   [deterministico]
   |      extrai CPF/data
   |      se nao houver dado: regras (+ LLM se a msg nao tem digitos)
   |         goodbye  -> encerra
   |         intencao bancaria -> guarda como pending_intent e pede o CPF
   |         greeting -> re-pergunta educadamente (nao conta tentativa)
   |         outro    -> "CPF invalido" (conta tentativa se tinha digitos)
   |      3 falhas -> sessao travada
   |      autenticou com pending_intent? -> executa a intencao direto
   |
   +-- AUTHENTICATED                            [regras -> LLM]
   |      classify_intent(mensagem)
   |      oferta pendente ("Deseja aumento?"):
   |         confirm -> aceita | reject ou "nao quero aumento" -> descarta
   |         None    -> repete a pergunta | outra intencao -> troca de assunto
   |      dispatch: limite | aumento | entrevista | cambio | greeting | off_topic | menu
   |
   +-- CREDIT_INCREASE_FLOW / INTERVIEW_* / EXCHANGE_*   [deterministico]
          1. tenta extrair o dado esperado (valor, emprego, moeda, sim/nao)
          2. se falhar, "escape hatch" por regras:
                cancelar/voltar/menu -> volta ao menu
                goodbye              -> encerra
                outra intencao bancaria -> troca de fluxo
          3. senao, mensagem de ajuda especifica do NaturalLanguageParser
```

## Onde o LLM e chamado (e onde nao e)

| Momento | LLM? | Motivo |
|---------|------|--------|
| Mensagem com palavra-chave clara ("meu limite", "sim", "tchau") | Nao | Regras respondem em 0 ms |
| Mensagem autenticada sem palavra-chave ("acho que nao precisa") | Sim (timeout 2,5 s) | Semantica |
| CPF, data, valores, moedas dentro de um fluxo | Nao | Parse deterministico |
| Mensagem sem digitos antes da autenticacao | Sim, se as regras falharem | Detectar despedida/intencao |
| Humanizacao de mensagens da autenticacao, saudacoes, despedidas | Sim (timeout 4 s) | Tom natural |
| Resultados com numeros (limite, cotacao, score) | Nao | Dados exatos, sem alucinacao |

Latencia por turno: 0 ms (regras) ou ate 2,5 s (LLM ambiguo) para intencao, mais ate 4 s de
humanizacao quando aplicavel. Em caso de timeout ou erro, o fallback e imediato.

## Melhorias de conversa que vieram com a V2

- **Intencao antes do login**: "quero ver meu limite" -> pede CPF -> autentica -> mostra o limite sem perguntar de novo
- **Cambio em um turno**: "cotacao do dolar" responde USD->BRL direto; "euro em reais" resolve o par
- **Valor na propria frase**: "quero aumentar para 20 mil" processa sem pedir o valor
- **Saida de fluxos**: "cancelar", "qual meu limite?", "tchau" funcionam no meio da entrevista
- **Negacao em oferta**: "nao quero aumento" e recusa, nao pedido de aumento
- **Formato brasileiro**: R$ 15.000,00
- **Limite de tentativas** (3) na autenticacao do chat, como no endpoint `/triage/authenticate`
- **Sessoes com TTL** e historico limitado: sem crescimento infinito de memoria
- **Oferta respondida com valor**: depois de "Deseja solicitar aumento?", "20 mil" ja processa o pedido
  (e "nao, 20 mil e muito" continua sendo recusa)
- **Sessao expirada explicada**: um `session_id` desconhecido (TTL ou reinicio) recebe
  "sua sessao anterior expirou, vamos recomecar" em vez de um pedido de CPF do nada
- **CPF incompleto**: "encontrei so 7 digitos, o CPF tem 11" em vez de "CPF invalido"
- **Data implausivel**: ano no futuro ou idade acima de 120 anos e apontado como erro de digitacao
- **Lembrete de saida**: apos duas respostas seguidas nao compreendidas num fluxo, a ajuda inclui
  "diga 'cancelar' para voltar ao menu"; `available_actions` traz `cancelar` dentro dos fluxos
- **Resultado da entrevista** explica se o score subiu, caiu ou se manteve
- **Mensagens longas demais** (> `MAX_MESSAGE_LENGTH`) recebem um pedido de resumo, sem erro 422

## Resiliencia

- Qualquer excecao dentro de `process_message` (CSV, API externa, bug) vira uma resposta de chat
  ("tive um problema tecnico...") com a sessao preservada, em vez de um HTTP 500
- O handler global de excecoes do FastAPI registra o traceback e devolve `{"detail": ...}` estavel
- O bloqueio por CPF em `/triage/authenticate` expira (`AUTH_LOCKOUT_MINUTES`, 15 min por padrao):
  antes, tres erros trancavam o CPF ate o processo reiniciar
- Um unico conjunto de agentes/servicos e instanciado em `routes.py` e injetado no orquestrador
  (antes cada agente criava seus proprios servicos, e o orquestrador instanciava um `TriageAgent`
  que nunca usava)

## Melhorias de velocidade

- Cliente LLM reaproveitado (pool de conexoes HTTP) em vez de instanciar `ChatOpenAI` a cada chamada
- Regras primeiro: a maior parte das mensagens nao chama o LLM
- Timeouts explicitos (2,5 s intencao, 4 s humanizacao) com `asyncio.wait_for` e `max_retries=1`
- Cache LRU de intencoes por mensagem normalizada
- Cliente HTTP compartilhado e timeout de 4 s na API de cambio (antes 10 s por API, em sequencia)

## Seguranca

O LLM **nao**: acessa CSV, gera tokens JWT, aprova/reprova limites, calcula scores ou altera dados.

O LLM **pode**: classificar a intencao, sugerir o agente e reescrever o texto de resposta.

## Por que o rascunho `orchestrator_v2.py` nao foi adotado como esta

- Chamava `classify_intent` em **toda** mensagem, inclusive numeros e CPF (uma chamada de LLM por turno)
- Dependia dos intents `goodbye` e `confirm`, que o `LLMService` da epoca nao produzia: despedida e "sim" nunca funcionariam
- `AgentRouter`/`RouterDecision` eram codigo morto
- Trocava os valores de `state` e `current_agent` que o front-end e os testes consomem

As partes boas foram portadas para o orquestrador atual, coberto por `tests/test_conversation_ux.py`.

## Proximos Passos

1. Persistir sessoes fora do processo (Redis) para escalar horizontalmente
2. Streaming da resposta humanizada
3. Entrevista conversacional (LLM extrai varios campos de uma frase so, com validacao deterministica)
4. Contar tentativas de autenticacao do chat tambem por CPF (hoje e por sessao; abrir uma sessao
   nova zera o contador)
5. Revisar a formula da entrevista: a media com o score anterior faz perfis bons (score > ~580)
   perderem pontos mesmo com dados excelentes, e o status `pending_analysis` nunca e produzido
