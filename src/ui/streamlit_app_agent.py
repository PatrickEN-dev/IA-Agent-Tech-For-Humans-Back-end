import asyncio
import time
from datetime import datetime
from enum import Enum

import streamlit as st

from api_client import APIClient


class AgentState(Enum):
    WELCOME = "welcome"
    COLLECTING_CPF = "collecting_cpf"
    COLLECTING_BIRTHDATE = "collecting_birthdate"
    AUTHENTICATED = "authenticated"
    CHAT = "chat"
    GOODBYE = "goodbye"


def init_session_state():
    defaults = {
        "messages": [],
        "current_state": AgentState.WELCOME,
        "cpf": None,
        "birthdate": None,
        "token": None,
        "client_name": None,
        "authenticated": False,
        "api_client": APIClient(),
        "auth_attempts": 0,
        "waiting_for_limit_value": False,
        "waiting_for_currency": False,
        "last_error": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_session():
    keys_to_delete = list(st.session_state.keys())
    for key in keys_to_delete:
        del st.session_state[key]
    init_session_state()


def add_message(role: str, content: str):
    st.session_state.messages.append(
        {
            "role": role,
            "content": content,
            "timestamp": datetime.now().strftime("%H:%M"),
        }
    )


def set_state(new_state: AgentState):
    st.session_state.current_state = new_state


def handle_welcome():
    add_message(
        "assistant",
        """
**Olá! Bem-vindo ao Banco Ágil** 🏦

Sou seu assistente virtual inteligente e estou aqui para ajudá-lo.

Para começarmos, preciso validar sua identidade.

**Por favor, digite seu CPF** (apenas números):

_Exemplo: 12345678901_
    """.strip(),
    )
    set_state(AgentState.COLLECTING_CPF)


def handle_cpf_collection(user_input: str):
    add_message("user", user_input)
    cpf_clean = user_input.replace(".", "").replace("-", "").replace(" ", "")

    if not cpf_clean.isdigit():
        add_message(
            "assistant",
            """
⚠️ **CPF inválido - Apenas números**

O CPF deve conter apenas números (sem pontos, traços ou letras).

📝 Por favor, digite novamente seu CPF:
        """.strip(),
        )
        return

    if len(cpf_clean) != 11:
        add_message(
            "assistant",
            """
⚠️ **CPF inválido - Tamanho incorreto**

O CPF deve ter exatamente 11 dígitos.

Você digitou: **{} dígitos**

📝 Por favor, digite novamente seu CPF:
        """.format(
                len(cpf_clean)
            ).strip(),
        )
        return

    st.session_state.cpf = cpf_clean
    add_message(
        "assistant",
        """
✅ **CPF recebido com sucesso!**

Agora preciso confirmar sua identidade.

**Por favor, digite sua data de nascimento** no formato **DD/MM/AAAA**:

📅 _Exemplo: 15/05/1990_
    """.strip(),
    )
    set_state(AgentState.COLLECTING_BIRTHDATE)


def handle_birthdate_collection(user_input: str):
    add_message("user", user_input)
    from datetime import date, datetime

    user_input = user_input.strip()

    if not user_input:
        add_message(
            "assistant",
            "⚠️ **Data não informada**\n\nPor favor, digite sua data de nascimento no formato DD/MM/AAAA:",
        )
        return

    if "/" in user_input:
        parts = user_input.split("/")
        if len(parts) == 3:
            try:
                day, month, year = map(int, parts)

                if year < 1900 or year > datetime.now().year:
                    add_message(
                        "assistant",
                        f"⚠️ **Ano inválido**\n\nO ano deve estar entre 1900 e {datetime.now().year}\n\nPor favor, digite novamente:",
                    )
                    return

                if month < 1 or month > 12:
                    add_message(
                        "assistant",
                        "⚠️ **Mês inválido**\n\nO mês deve estar entre 1 e 12\n\nPor favor, digite novamente:",
                    )
                    return

                birthdate_obj = date(year, month, day)

            except ValueError as e:
                print(f"[DEBUG] Erro ao criar data: {e}")
                add_message(
                    "assistant",
                    """
⚠️ **Data inválida**

Verifique se o dia existe no mês informado.

Use o formato DD/MM/AAAA (exemplo: 15/05/1990)

Por favor, digite novamente:
                """.strip(),
                )
                return
        else:
            add_message(
                "assistant",
                """
⚠️ **Formato inválido**

Use o formato DD/MM/AAAA (exemplo: 15/05/1990)
            """.strip(),
            )
            return
    else:
        add_message(
            "assistant",
            """
⚠️ **Formato inválido**

Use o formato DD/MM/AAAA (exemplo: 15/05/1990)
        """.strip(),
        )
        return

    st.session_state.birthdate = birthdate_obj
    add_message("assistant", "🔄 **Validando suas informações...**")

    try:
        asyncio.run(authenticate_user())
    except Exception as e:
        print(f"[ERROR] Erro no asyncio.run: {e}")
        add_message(
            "assistant",
            "❌ **Erro Interno**\n\nOcorreu um problema técnico.\n\nTente reiniciar a sessão.",
        )
        return

    st.rerun()


async def authenticate_user():
    print(
        f"[DEBUG] Iniciando autenticação - CPF: {st.session_state.cpf}, Data: {st.session_state.birthdate}"
    )

    try:
        api_client = st.session_state.api_client

        if not await api_client.health_check():
            add_message(
                "assistant",
                "❌ **Erro de Conexão**\n\nO sistema está temporariamente indisponível.\n\nTente novamente em alguns minutos.",
            )
            return

        result = await api_client.authenticate(
            st.session_state.cpf,
            st.session_state.birthdate,
            "Ola, quero ajuda",
        )
        print(f"[DEBUG] Resultado autenticação: {result}")
    except Exception as e:
        print(f"[ERROR] Erro na autenticação: {e}")
        add_message(
            "assistant",
            "❌ **Erro Técnico**\n\nOcorreu um problema durante a autenticação.\n\nTente novamente em alguns minutos.",
        )
        return

    if result.get("authenticated"):
        print("[DEBUG] Autenticação bem-sucedida!")
        st.session_state.authenticated = True
        st.session_state.token = result.get("token")
        st.session_state.auth_attempts = 0
        st.session_state.last_error = None

        try:
            credit_info = await api_client.get_credit_limit()
            if "error" not in credit_info:
                st.session_state.client_name = credit_info.get("cpf", "Cliente")
        except Exception as e:
            print(f"[DEBUG] Erro ao buscar informações de crédito: {e}")

        add_message(
            "assistant",
            f"""
🎉 **Autenticação realizada com sucesso!**

Seja bem-vindo(a)!

**Como posso ajudá-lo(a) hoje?**

Você pode me perguntar sobre:
- 💳 Seu limite de crédito
- 📈 Solicitar aumento de limite
- 💱 Cotação de moedas
- 📋 Atualizar seu perfil financeiro

Digite sua pergunta ou solicitação:
        """.strip(),
        )
        set_state(AgentState.CHAT)
    else:
        print(f"[DEBUG] Falha na autenticação: {result}")
        st.session_state.auth_attempts += 1
        st.session_state.last_error = result.get("error", "Erro desconhecido")
        remaining = 3 - st.session_state.auth_attempts

        if remaining <= 0:
            add_message(
                "assistant",
                """
🔒 **Acesso bloqueado**

Você excedeu o número máximo de tentativas.

Por segurança, o atendimento será encerrado.

📞 Entre em contato: **0800-123-4567**
            """.strip(),
            )
            set_state(AgentState.GOODBYE)
        else:
            error_msg = result.get("error", {})
            add_message(
                "assistant",
                f"""
❌ **Dados não conferem**

Você ainda tem **{remaining} tentativa(s)**.

Vamos recomeçar. Digite seu **CPF**:
            """.strip(),
            )
            st.session_state.cpf = None
            st.session_state.birthdate = None
            set_state(AgentState.COLLECTING_CPF)


async def handle_chat_message(user_input: str):
    add_message("user", user_input)
    api_client = st.session_state.api_client

    if not await api_client.health_check():
        add_message(
            "assistant",
            "❌ **Serviço Indisponível**\n\nO sistema está temporariamente fora do ar.\n\nTente novamente em alguns minutos.",
        )
        return

    lower_input = user_input.lower()

    if any(
        word in lower_input
        for word in ["sair", "tchau", "adeus", "encerrar", "bye", "exit"]
    ):
        add_message(
            "assistant",
            f"""
🏦 **Obrigado pela visita!**

Foi um prazer atendê-lo no Banco Ágil.

Esperamos vê-lo novamente em breve! 😊

---
_Clique em "Novo Atendimento" para iniciar uma nova conversa._
        """.strip(),
        )
        set_state(AgentState.GOODBYE)
        return

    if any(word in lower_input for word in ["limite", "credito", "crédito", "saldo"]):
        add_message("assistant", "🔄 **Consultando seu limite...**")
        result = await api_client.get_credit_limit()

        if "error" not in result:
            add_message(
                "assistant",
                f"""
💳 **Informações do Seu Crédito**

| Informação | Valor |
|------------|-------|
| CPF | {result['cpf']} |
| Score | **{result['score']}** pontos |
| Limite Total | **R$ {result['current_limit']:,.2f}** |
| Limite Disponível | **R$ {result['available_limit']:,.2f}** |

**O que mais posso fazer por você?**
            """.strip(),
            )
        else:
            add_message("assistant", f"❌ Erro: {result.get('error')}")
        return

    if any(
        word in lower_input for word in ["aumento", "aumentar", "mais limite", "elevar"]
    ):
        add_message(
            "assistant",
            """
📈 **Solicitação de Aumento de Limite**

Para processar sua solicitação, informe o **valor desejado** para o novo limite.

💰 Digite o valor em R$ (exemplo: 25000):
        """.strip(),
        )
        st.session_state.waiting_for_limit_value = True
        return

    if st.session_state.get("waiting_for_limit_value"):
        try:
            value = float(
                user_input.replace("R$", "").replace(".", "").replace(",", ".").strip()
            )
            add_message("assistant", "🔄 **Processando solicitação...**")
            result = await api_client.request_limit_increase(value)

            if "error" not in result:
                status_emoji = {
                    "approved": "🎉",
                    "pending_analysis": "⏳",
                    "denied": "😔",
                }
                emoji = status_emoji.get(result["status"], "ℹ️")

                add_message(
                    "assistant",
                    f"""
{emoji} **Resultado da Solicitação**

{result['message']}

**O que mais posso fazer por você?**
                """.strip(),
                )
            else:
                add_message("assistant", f"❌ Erro: {result.get('error')}")

            st.session_state.waiting_for_limit_value = False
        except ValueError:
            add_message(
                "assistant",
                """
⚠️ **Valor inválido**

Por favor, informe um valor numérico (exemplo: 25000)
            """.strip(),
            )
        return

    if any(
        word in lower_input
        for word in ["cambio", "câmbio", "dolar", "dólar", "euro", "moeda", "cotacao"]
    ):
        add_message(
            "assistant",
            """
💱 **Consulta de Cotação de Moedas**

Moedas disponíveis:
- 🇺🇸 **USD** - Dólar Americano
- 🇪🇺 **EUR** - Euro
- 🇬🇧 **GBP** - Libra Esterlina
- 🇯🇵 **JPY** - Iene Japonês
- 🇦🇷 **ARS** - Peso Argentino

Digite o código da moeda (3 letras) para conversão de BRL:
        """.strip(),
        )
        st.session_state.waiting_for_currency = True
        return

    if st.session_state.get("waiting_for_currency"):
        currency = user_input.strip().upper()
        if len(currency) == 3 and currency.isalpha():
            add_message("assistant", "🔄 **Consultando cotação...**")
            result = await api_client.get_exchange_rate("BRL", currency)

            if "error" not in result:
                add_message(
                    "assistant",
                    f"""
💱 **Cotação {result['from_currency']}/{result['to_currency']}**

| Informação | Valor |
|------------|-------|
| Taxa | **1 {result['from_currency']} = {result['rate']:.4f} {result['to_currency']}** |
| Atualização | {result['timestamp']} |

{result['message']}

**O que mais posso fazer por você?**
                """.strip(),
                )
            else:
                add_message("assistant", f"❌ {result.get('error')}")

            st.session_state.waiting_for_currency = False
        else:
            add_message(
                "assistant",
                """
⚠️ **Código inválido**

Digite um código de moeda com 3 letras (USD, EUR, GBP, etc.)
            """.strip(),
            )
        return

    add_message(
        "assistant",
        """
🤔 **Como posso ajudá-lo?**

Posso ajudá-lo com:
- 💳 Consultar seu limite de crédito
- 📈 Solicitar aumento de limite
- 💱 Consultar cotação de moedas
- 🚪 Encerrar atendimento (digite "sair")

Digite o que você gostaria de fazer:
    """.strip(),
    )


def process_user_input(user_input: str):
    if not user_input or not user_input.strip():
        return

    user_input = user_input.strip()
    current_state = st.session_state.current_state

    if current_state == AgentState.GOODBYE:
        return

    print(f"[DEBUG] Processando input no estado: {current_state.value}")
    print(f"[DEBUG] Input do usuário: '{user_input}'")

    try:
        if current_state == AgentState.COLLECTING_CPF:
            handle_cpf_collection(user_input)
        elif current_state == AgentState.COLLECTING_BIRTHDATE:
            handle_birthdate_collection(user_input)
        elif current_state == AgentState.AUTHENTICATED:
            set_state(AgentState.CHAT)
            asyncio.run(handle_chat_message(user_input))
        elif current_state == AgentState.CHAT:
            asyncio.run(handle_chat_message(user_input))
    except Exception as e:
        print(f"[ERROR] Erro ao processar input: {e}")
        add_message(
            "assistant",
            f"""
❌ **Erro Técnico**

Ocorreu um problema ao processar sua solicitação.

Detalhes para suporte: {str(e)[:100]}...

**Opções:**
- 🔄 Digite novamente sua solicitação
- 🏠 Use "sair" para reiniciar
        """.strip(),
        )


def apply_custom_css():
    st.markdown(
        """
    <style>
    .stApp {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    }

    .main .block-container {
        padding: 1rem 2rem 2rem 2rem;
        max-width: 900px;
    }

    .header-container {
        background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
        border-radius: 16px;
        padding: 2rem;
        margin-bottom: 1.5rem;
        text-align: center;
        box-shadow: 0 10px 40px rgba(59, 130, 246, 0.3);
    }

    .header-container h1 {
        color: white;
        font-size: 2rem;
        font-weight: 700;
        margin: 0;
    }

    .stButton > button {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
        color: white;
        border: none;
        border-radius: 12px;
        padding: 0.75rem 1.5rem;
        font-weight: 600;
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """,
        unsafe_allow_html=True,
    )


def render_header():
    """Renderiza o header."""
    st.markdown(
        """
    <div class="header-container">
        <h1>🏦 Banco Ágil</h1>
        <p>Sistema de Atendimento Digital com IA</p>
    </div>
    """,
        unsafe_allow_html=True,
    )


def render_chat():
    """Renderiza o histórico do chat."""
    chat_container = st.container(height=450)

    with chat_container:
        if not st.session_state.messages:
            st.info("💬 Iniciando atendimento...")
            return

        for msg in st.session_state.messages:
            role = msg["role"]
            content = msg["content"]
            timestamp = msg.get("timestamp", "")

            with st.chat_message(role, avatar="🤖" if role == "assistant" else "👤"):
                st.markdown(content)
                if timestamp:
                    st.caption(f"🕐 {timestamp}")


def render_input():
    """Renderiza área de input."""
    current_state = st.session_state.current_state

    if current_state == AgentState.GOODBYE:
        st.divider()
        if st.button("🔄 Iniciar Novo Atendimento", use_container_width=True):
            reset_session()
            st.rerun()
        return

    placeholders = {
        AgentState.COLLECTING_CPF: "Digite seu CPF (apenas números)...",
        AgentState.COLLECTING_BIRTHDATE: "Digite sua data de nascimento (DD/MM/AAAA)...",
        AgentState.AUTHENTICATED: "Digite sua mensagem...",
        AgentState.CHAT: "Digite sua mensagem...",
    }
    placeholder = placeholders.get(current_state, "Digite sua mensagem...")

    user_input = st.chat_input(placeholder=placeholder)

    if user_input:
        process_user_input(user_input)
        st.rerun()


def main():
    st.set_page_config(
        page_title="Banco Ágil - Chat com IA",
        page_icon="🏦",
        layout="centered",
        initial_sidebar_state="collapsed",
    )

    apply_custom_css()
    init_session_state()

    render_header()

    if "api_health_checked" not in st.session_state:
        st.session_state.api_health_checked = True

        with st.spinner("🔍 Verificando conexão com o sistema..."):
            api_client = APIClient()
            try:
                if asyncio.run(api_client.health_check()):
                    st.success("✅ Sistema online e funcionando!")
                    time.sleep(1)  # Breve pausa para mostrar o status
                else:
                    st.error("🔴 Sistema temporariamente indisponível")
                    st.info("💡 Verifique se a API está rodando na porta 8000")
                    return
            except Exception as e:
                st.error(f"🔴 Erro de conexão: {str(e)}")
                st.info("💡 Verifique se a API está rodando na porta 8000")
                return

    if st.session_state.current_state == AgentState.WELCOME:
        handle_welcome()
        st.rerun()

    render_chat()
    render_input()

    # Sidebar com info
    with st.sidebar:
        st.markdown("### 🧪 CPFs de Teste")
        st.markdown(
            """
        **Maria Silva**
        - CPF: `12345678901`
        - Data: `15/05/1990`
        - Score: 750

        **João Santos**
        - CPF: `98765432100`
        - Data: `22/03/1985`
        - Score: 600

        **Ana Oliveira**
        - CPF: `11122233344`
        - Data: `08/11/1992`
        - Score: 850
        """
        )

        st.divider()

        if st.button("🔄 Reiniciar Sessão"):
            reset_session()
            st.rerun()


if __name__ == "__main__":
    main()
