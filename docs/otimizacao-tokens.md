# Otimização de Consumo de Tokens nos Prompts

## Contexto

Durante o desenvolvimento do projeto, identifiquei que os prompts enviados para a LLM estavam consumindo mais tokens do que o necessário. Inicialmente, tive dificuldade em entender exatamente como os tokens são contabilizados e quais estratégias usar para otimizar. Com a ajuda da IA, consegui compreender melhor o problema e implementar as melhorias.

## O que aprendi

- Espaços, quebras de linha e formatação contam como tokens
- Prefixos longos como "Cliente:" podem ser substituídos por "U:" sem perder clareza para o modelo
- Instruções verbosas podem ser compactadas mantendo o mesmo significado semântico
- Cada token economizado por chamada se multiplica pelo volume de requisições

## Alterações Realizadas

### 1. llm_service.py

#### Prompt de Classificação de Intent (linha 259)

**Antes:**
```python
template = """Intent: credit_limit|request_increase|exchange_rate|interview|other
"{message}"
→"""
```

**Depois:**
```python
template = "Intent:credit_limit|request_increase|exchange_rate|interview|other\n\"{message}\"→"
```

**Economia:** ~5 tokens por chamada

---

#### Prompt de Geração de Resposta (linha 359)

**Antes:**
```python
template = """Banco Ágil. Responda em 1-2 frases.
{prompt}"""
```

**Depois:**
```python
template = "Banco Ágil.1-2 frases.\n{prompt}"
```

**Economia:** ~8 tokens por chamada

---

#### Prompt de Humanização (linhas 422-433)

**Antes:**
```python
name_part = f"Cliente: {user_name}. " if user_name else ""
ctx = f"[Anterior: {last.get('content', '')[:60]}...]\n"

system_prompt = f"""Banco Ágil - Humanize esta resposta em 1-2 frases naturais.
{name_part}{ctx}
User: "{user_message}"
Tech: "{technical_response}"
→ Resposta amigável (mantenha info essencial, cumprimente se saudação):"""
```

**Depois:**
```python
name_part = f"[{user_name}]" if user_name else ""
ctx = f"[Ant:{last.get('content', '')[:50]}]"

system_prompt = f"""Banco Ágil.Humanize 1-2 frases.{name_part}{ctx}
U:"{user_message}"
T:"{technical_response}"
→"""
```

**Economia:** ~20 tokens por chamada

---

### 2. optimized_chat.py

#### Contexto Base do Sistema (linhas 309-323)

**Antes:**
```python
base_context = """Assistente Banco Ágil. IMPORTANTE: Responda APENAS questões bancárias (limite, crédito, câmbio, perfil).
Serviços: limite, aumento, câmbio, perfil.
NUNCA responda matemática, história, tecnologia, ou outros assuntos.

"""
```

**Depois:**
```python
base = "Banco Ágil.Só bancário(limite/crédito/câmbio/perfil).Rejeite outros temas."
```

**Economia:** ~30 tokens por chamada

---

#### Formatação do Histórico (linhas 334-338)

**Antes:**
```python
role = "Cliente" if msg["role"] == "user" else "Você"
prompt += f"{role}: {msg['content']}\n"
prompt += "Resposta concisa, profissional, máximo 2 frases."
```

**Depois:**
```python
role = "U" if msg["role"] == "user" else "A"
prompt += f"{role}:{msg['content']}\n"
prompt += f"U:{current_message}\n→Max 2 frases:"
```

**Economia:** ~8 tokens por mensagem no histórico + ~10 tokens na instrução final

---

## Resumo da Economia

| Componente | Economia por chamada |
|------------|---------------------|
| Classificação de intent | ~5 tokens |
| Geração de resposta | ~8 tokens |
| Humanização | ~20 tokens |
| Contexto base | ~30 tokens |
| Histórico (por msg) | ~8 tokens |
| Instrução final | ~10 tokens |

### Estimativa Total

- **Por interação completa:** ~50-60 tokens economizados
- **Com 100 interações/dia:** ~5.000-6.000 tokens/dia
- **Redução percentual:** ~15-20% no consumo de tokens dos prompts

## Observações

As otimizações mantêm a qualidade das respostas da LLM. O modelo consegue interpretar prompts compactos da mesma forma que prompts verbosos, desde que a estrutura e a semântica sejam preservadas.
