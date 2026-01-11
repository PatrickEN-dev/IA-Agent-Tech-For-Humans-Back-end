import asyncio
import sys
import time
from datetime import datetime
from enum import Enum

import streamlit as st

sys.path.insert(0, str(__file__).replace("src/ui/streamlit_app_agent.py", ""))

from api_client import APIClient
from src.utils.text_normalizer import extract_cpf_from_text, parse_date_from_text, parse_boolean_response
from src.services.llm_service import NaturalLanguageParser


class AgentState(Enum):
    WELCOME = "welcome"
    COLLECTING_CPF = "collecting_cpf"
    COLLECTING_BIRTHDATE = "collecting_birthdate"
    AUTHENTICATED = "authenticated"
    CHAT = "chat"
    GOODBYE = "goodbye"
    INTERVIEW_INCOME = "interview_income"
    INTERVIEW_EMPLOYMENT = "interview_employment"
    INTERVIEW_EXPENSES = "interview_expenses"
    INTERVIEW_DEPENDENTS = "interview_dependents"
    INTERVIEW_DEBTS = "interview_debts"
    INTERVIEW_CONFIRM = "interview_confirm"


nl_parser = NaturalLanguageParser()


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
        "interview_data": {"renda_mensal": None, "tipo_emprego": None, "despesas": None, "num_dependentes": None, "tem_dividas": None},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_session():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    init_session_state()


def add_message(role: str, content: str):
    st.session_state.messages.append({"role": role, "content": content, "timestamp": datetime.now().strftime("%H:%M")})


def set_state(new_state: AgentState):
    st.session_state.current_state = new_state


def handle_welcome():
    add_message("assistant", "**Olá! Bem-vindo ao Banco Ágil**\n\nPara começar, informe seu CPF (com ou sem pontos/traço):")
    set_state(AgentState.COLLECTING_CPF)


def handle_cpf_collection(user_input: str):
    add_message("user", user_input)
    cpf_clean = extract_cpf_from_text(user_input)

    if cpf_clean is None:
        lower_input = user_input.lower()
        if any(w in lower_input for w in ["não sei", "esqueci", "não lembro", "onde", "como"]):
            add_message("assistant", "O CPF tem 11 dígitos e aparece em documentos como RG ou CNH. Quando tiver, digite aqui.")
            return
        add_message("assistant", "Não consegui identificar o CPF. Digite os 11 números (ex: 12345678901):")
        return

    if len(cpf_clean) != 11:
        add_message("assistant", f"O CPF deve ter 11 dígitos. Você digitou {len(cpf_clean)}. Tente novamente:")
        return

    st.session_state.cpf = cpf_clean
    add_message("assistant", "CPF recebido!\n\n**Qual é sua data de nascimento?** (ex: 15/05/1990 ou 15 de maio de 1990)")
    set_state(AgentState.COLLECTING_BIRTHDATE)


def handle_birthdate_collection(user_input: str):
    add_message("user", user_input)
    from datetime import date

    if not user_input.strip():
        add_message("assistant", "Por favor, informe sua data de nascimento.")
        return

    date_parts = parse_date_from_text(user_input)

    if date_parts is None:
        if any(w in user_input.lower() for w in ["não sei", "não lembro", "esqueci"]):
            add_message("assistant", "A data de nascimento é necessária. Confira em um documento (RG/CNH) e informe no formato dia/mês/ano.")
            return
        add_message("assistant", "Não entendi a data. Informe no formato dia/mês/ano (ex: 15/05/1990):")
        return

    day, month, year = date_parts
    current_year = datetime.now().year

    if year < 1900 or year > current_year:
        add_message("assistant", f"O ano deve estar entre 1900 e {current_year}. Tente novamente:")
        return
    if month < 1 or month > 12:
        add_message("assistant", "O mês deve estar entre 1 e 12. Tente novamente:")
        return

    try:
        birthdate_obj = date(year, month, day)
    except ValueError:
        add_message("assistant", "Data inválida. Verifique se o dia existe no mês informado e tente novamente:")
        return

    st.session_state.birthdate = birthdate_obj
    add_message("assistant", "Validando suas informações...")

    try:
        asyncio.run(authenticate_user())
    except Exception as e:
        print(f"[ERROR] {e}")
        add_message("assistant", "Ocorreu um problema técnico. Por favor, tente novamente.")
        return

    st.rerun()


async def authenticate_user():
    api_client = st.session_state.api_client

    if not await api_client.health_check():
        add_message("assistant", "Sistema indisponível. Tente novamente em alguns minutos.")
        return

    result = await api_client.authenticate(st.session_state.cpf, st.session_state.birthdate, "Ola, quero ajuda")

    if result.get("authenticated"):
        st.session_state.authenticated = True
        st.session_state.token = result.get("token")
        st.session_state.auth_attempts = 0

        try:
            credit_info = await api_client.get_credit_limit()
            if "error" not in credit_info:
                st.session_state.client_name = credit_info.get("cpf", "Cliente")
        except:
            pass

        add_message("assistant", "**Autenticação realizada com sucesso!**\n\nComo posso ajudá-lo?\n- Ver limite de crédito\n- Solicitar aumento\n- Cotação de moedas\n- Atualizar perfil financeiro")
        set_state(AgentState.CHAT)
    else:
        st.session_state.auth_attempts += 1
        remaining = 3 - st.session_state.auth_attempts

        if remaining <= 0:
            add_message("assistant", "**Acesso bloqueado**\n\nVocê excedeu o número de tentativas.\n\nContato: 0800-123-4567")
            set_state(AgentState.GOODBYE)
        else:
            add_message("assistant", f"**Dados não conferem.**\n\nVocê tem {remaining} tentativa(s).\n\nDigite seu CPF novamente:")
            st.session_state.cpf = None
            st.session_state.birthdate = None
            set_state(AgentState.COLLECTING_CPF)


async def handle_chat_message(user_input: str):
    add_message("user", user_input)
    api_client = st.session_state.api_client

    if not await api_client.health_check():
        add_message("assistant", "Sistema indisponível. Tente novamente em alguns minutos.")
        return

    lower_input = user_input.lower()

    if any(w in lower_input for w in ["sair", "tchau", "adeus", "encerrar", "bye", "exit", "até logo"]):
        add_message("assistant", "**Obrigado pela visita ao Banco Ágil!**\n\nAté a próxima!")
        set_state(AgentState.GOODBYE)
        return

    if any(w in lower_input for w in ["limite", "credito", "crédito", "saldo", "quanto tenho"]):
        add_message("assistant", "Consultando seu limite...")
        result = await api_client.get_credit_limit()

        if "error" not in result:
            add_message("assistant", f"**Seu Crédito**\n\n| Info | Valor |\n|------|-------|\n| Score | **{result['score']}** |\n| Limite Total | **R$ {result['current_limit']:,.2f}** |\n| Disponível | **R$ {result['available_limit']:,.2f}** |\n\nO que mais posso fazer?")
        else:
            add_message("assistant", f"Erro: {result.get('error')}")
        return

    if any(w in lower_input for w in ["aumento", "aumentar", "mais limite", "elevar", "subir limite"]):
        value, _ = nl_parser.parse_limit_value(user_input)

        if value is not None:
            add_message("assistant", "Processando solicitação...")
            result = await api_client.request_limit_increase(value)

            if "error" not in result:
                status_msg = {"approved": "Aprovada!", "pending_analysis": "Em análise.", "denied": "Negada."}
                add_message("assistant", f"**Resultado:** {status_msg.get(result['status'], '')}\n\n{result['message']}\n\nO que mais posso fazer?")
            else:
                add_message("assistant", f"Erro: {result.get('error')}")
            return

        add_message("assistant", "**Aumento de Limite**\n\nQual valor deseja? (ex: 25000, 25k)")
        st.session_state.waiting_for_limit_value = True
        return

    if st.session_state.get("waiting_for_limit_value"):
        value, error_msg = nl_parser.parse_limit_value(user_input)

        if value is None:
            add_message("assistant", error_msg)
            return

        add_message("assistant", "Processando solicitação...")
        result = await api_client.request_limit_increase(value)

        if "error" not in result:
            status_msg = {"approved": "Aprovada!", "pending_analysis": "Em análise.", "denied": "Negada."}
            add_message("assistant", f"**Resultado:** {status_msg.get(result['status'], '')}\n\n{result['message']}\n\nO que mais posso fazer?")
        else:
            add_message("assistant", f"Erro: {result.get('error')}")

        st.session_state.waiting_for_limit_value = False
        return

    if any(w in lower_input for w in ["cambio", "câmbio", "dolar", "dólar", "euro", "moeda", "cotacao", "cotação", "libra"]):
        currency, _ = nl_parser.parse_currency(user_input)

        if currency is not None:
            add_message("assistant", "Consultando cotação...")
            result = await api_client.get_exchange_rate("BRL", currency)

            if "error" not in result:
                add_message("assistant", f"**Cotação {result['from_currency']}/{result['to_currency']}**\n\n1 {result['from_currency']} = {result['rate']:.4f} {result['to_currency']}\n\n{result['message']}\n\nO que mais posso fazer?")
            else:
                add_message("assistant", f"Erro: {result.get('error')}")
            return

        add_message("assistant", "**Cotação de Moedas**\n\nQual moeda? USD (dólar), EUR (euro), GBP (libra), JPY (iene), ARS (peso)")
        st.session_state.waiting_for_currency = True
        return

    if st.session_state.get("waiting_for_currency"):
        currency, error_msg = nl_parser.parse_currency(user_input)

        if currency is None:
            add_message("assistant", error_msg)
            return

        add_message("assistant", "Consultando cotação...")
        result = await api_client.get_exchange_rate("BRL", currency)

        if "error" not in result:
            add_message("assistant", f"**Cotação {result['from_currency']}/{result['to_currency']}**\n\n1 {result['from_currency']} = {result['rate']:.4f} {result['to_currency']}\n\n{result['message']}\n\nO que mais posso fazer?")
        else:
            add_message("assistant", f"Erro: {result.get('error')}")

        st.session_state.waiting_for_currency = False
        return

    if any(w in lower_input for w in ["entrevista", "perfil", "atualizar", "cadastro", "questionario", "questionário", "dados"]):
        start_interview()
        return

    add_message("assistant", "Posso ajudar com:\n- **\"Ver limite\"** - Consultar crédito\n- **\"Aumento de limite\"** - Solicitar aumento\n- **\"Cotação dólar\"** - Ver câmbio\n- **\"Atualizar perfil\"** - Entrevista financeira\n- **\"Sair\"** - Encerrar")


def start_interview():
    st.session_state.interview_data = {"renda_mensal": None, "tipo_emprego": None, "despesas": None, "num_dependentes": None, "tem_dividas": None}
    add_message("assistant", "**Vamos atualizar seu perfil!**\n\nIsso ajuda a melhorar seu score.\n\n**Qual é sua renda mensal?** (ex: 6 mil, R$ 5.500, 8k)")
    set_state(AgentState.INTERVIEW_INCOME)


def handle_interview_income(user_input: str):
    add_message("user", user_input)
    value, error_msg = nl_parser.parse_income(user_input)

    if value is None:
        add_message("assistant", error_msg)
        return

    st.session_state.interview_data["renda_mensal"] = value
    add_message("assistant", f"Renda: **R$ {value:,.2f}**\n\n**Tipo de trabalho?** (CLT, autônomo, MEI, servidor público, desempregado)")
    set_state(AgentState.INTERVIEW_EMPLOYMENT)


def handle_interview_employment(user_input: str):
    add_message("user", user_input)
    emp_type, error_msg = nl_parser.parse_employment_type(user_input)

    if emp_type is None:
        add_message("assistant", error_msg)
        return

    st.session_state.interview_data["tipo_emprego"] = emp_type
    emp_names = {"CLT": "CLT", "FORMAL": "Formal", "PUBLICO": "Servidor público", "AUTONOMO": "Autônomo", "MEI": "MEI", "DESEMPREGADO": "Desempregado"}
    add_message("assistant", f"Tipo: **{emp_names.get(emp_type, emp_type)}**\n\n**Qual o total de despesas mensais?** (aluguel, contas, alimentação, etc)")
    set_state(AgentState.INTERVIEW_EXPENSES)


def handle_interview_expenses(user_input: str):
    add_message("user", user_input)
    value, error_msg = nl_parser.parse_expenses(user_input)

    if value is None:
        add_message("assistant", error_msg)
        return

    st.session_state.interview_data["despesas"] = value
    add_message("assistant", f"Despesas: **R$ {value:,.2f}**\n\n**Quantos dependentes?** (filhos, cônjuge sem renda, pais)")
    set_state(AgentState.INTERVIEW_DEPENDENTS)


def handle_interview_dependents(user_input: str):
    add_message("user", user_input)
    value, error_msg = nl_parser.parse_dependents(user_input)

    if value is None:
        add_message("assistant", error_msg)
        return

    st.session_state.interview_data["num_dependentes"] = value
    dep_text = "nenhum" if value == 0 else str(value)
    add_message("assistant", f"Dependentes: **{dep_text}**\n\n**Possui alguma dívida em aberto?** (sim/não)")
    set_state(AgentState.INTERVIEW_DEBTS)


def handle_interview_debts(user_input: str):
    add_message("user", user_input)
    value, error_msg = nl_parser.parse_has_debts(user_input)

    if value is None:
        add_message("assistant", error_msg)
        return

    st.session_state.interview_data["tem_dividas"] = value
    data = st.session_state.interview_data
    emp_names = {"CLT": "CLT", "FORMAL": "Formal", "PUBLICO": "Servidor público", "AUTONOMO": "Autônomo", "MEI": "MEI", "DESEMPREGADO": "Desempregado"}

    add_message("assistant", f"**Resumo:**\n\n| Campo | Valor |\n|-------|-------|\n| Renda | R$ {data['renda_mensal']:,.2f} |\n| Trabalho | {emp_names.get(data['tipo_emprego'], data['tipo_emprego'])} |\n| Despesas | R$ {data['despesas']:,.2f} |\n| Dependentes | {data['num_dependentes']} |\n| Dívidas | {'Sim' if value else 'Não'} |\n\n**Confirma?** (sim/não)")
    set_state(AgentState.INTERVIEW_CONFIRM)


def handle_interview_confirm(user_input: str):
    add_message("user", user_input)
    confirmed = parse_boolean_response(user_input)

    if confirmed is None:
        add_message("assistant", "Não entendi. Confirma os dados? (sim/não)")
        return

    if not confirmed:
        add_message("assistant", "Ok! Vamos recomeçar.\n\n**Qual é sua renda mensal?**")
        st.session_state.interview_data = {"renda_mensal": None, "tipo_emprego": None, "despesas": None, "num_dependentes": None, "tem_dividas": None}
        set_state(AgentState.INTERVIEW_INCOME)
        return

    add_message("assistant", "Processando...")

    try:
        asyncio.run(submit_interview())
    except Exception as e:
        print(f"[ERROR] {e}")
        add_message("assistant", "Erro ao processar. Tente novamente mais tarde.")
        set_state(AgentState.CHAT)

    st.rerun()


async def submit_interview():
    api_client = st.session_state.api_client
    data = st.session_state.interview_data

    try:
        result = await api_client.submit_interview(
            renda_mensal=data["renda_mensal"],
            tipo_emprego=data["tipo_emprego"],
            despesas=data["despesas"],
            num_dependentes=data["num_dependentes"],
            tem_dividas=data["tem_dividas"],
        )

        if "error" not in result:
            score_diff = result["new_score"] - result["previous_score"]
            diff_text = f"+{score_diff}" if score_diff >= 0 else str(score_diff)
            add_message("assistant", f"**Perfil atualizado!**\n\n| Métrica | Valor |\n|---------|-------|\n| Score Anterior | {result['previous_score']} |\n| Score Atual | **{result['new_score']}** ({diff_text}) |\n\n**Recomendação:** {result['recommendation']}\n\nO que mais posso fazer?")
        else:
            add_message("assistant", f"Erro: {result.get('error')}")
    except Exception as e:
        print(f"[ERROR] {e}")
        add_message("assistant", "Erro ao processar. Tente novamente mais tarde.")

    set_state(AgentState.CHAT)


def process_user_input(user_input: str):
    if not user_input or not user_input.strip():
        return

    user_input = user_input.strip()
    current_state = st.session_state.current_state

    if current_state == AgentState.GOODBYE:
        return

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
        elif current_state == AgentState.INTERVIEW_INCOME:
            handle_interview_income(user_input)
        elif current_state == AgentState.INTERVIEW_EMPLOYMENT:
            handle_interview_employment(user_input)
        elif current_state == AgentState.INTERVIEW_EXPENSES:
            handle_interview_expenses(user_input)
        elif current_state == AgentState.INTERVIEW_DEPENDENTS:
            handle_interview_dependents(user_input)
        elif current_state == AgentState.INTERVIEW_DEBTS:
            handle_interview_debts(user_input)
        elif current_state == AgentState.INTERVIEW_CONFIRM:
            handle_interview_confirm(user_input)
    except Exception as e:
        print(f"[ERROR] {e}")
        add_message("assistant", "Ocorreu um problema. Tente novamente ou digite 'sair' para reiniciar.")


def apply_custom_css():
    st.markdown("""
    <style>
    .stApp { background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); }
    .main .block-container { padding: 1rem 2rem 2rem 2rem; max-width: 900px; }
    .header-container { background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%); border-radius: 16px; padding: 2rem; margin-bottom: 1.5rem; text-align: center; box-shadow: 0 10px 40px rgba(59, 130, 246, 0.3); }
    .header-container h1 { color: white; font-size: 2rem; font-weight: 700; margin: 0; }
    .stButton > button { background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); color: white; border: none; border-radius: 12px; padding: 0.75rem 1.5rem; font-weight: 600; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)


def render_header():
    st.markdown('<div class="header-container"><h1>Banco Ágil</h1><p>Atendimento Digital com IA</p></div>', unsafe_allow_html=True)


def render_chat():
    chat_container = st.container(height=450)
    with chat_container:
        if not st.session_state.messages:
            st.info("Iniciando atendimento...")
            return
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"], avatar="🤖" if msg["role"] == "assistant" else "👤"):
                st.markdown(msg["content"])
                if msg.get("timestamp"):
                    st.caption(msg["timestamp"])


def render_input():
    current_state = st.session_state.current_state

    if current_state == AgentState.GOODBYE:
        st.divider()
        if st.button("Novo Atendimento", use_container_width=True):
            reset_session()
            st.rerun()
        return

    placeholders = {
        AgentState.COLLECTING_CPF: "Digite seu CPF...",
        AgentState.COLLECTING_BIRTHDATE: "Digite sua data de nascimento...",
        AgentState.AUTHENTICATED: "Digite sua mensagem...",
        AgentState.CHAT: "Digite sua mensagem...",
        AgentState.INTERVIEW_INCOME: "Informe sua renda...",
        AgentState.INTERVIEW_EMPLOYMENT: "Informe seu tipo de trabalho...",
        AgentState.INTERVIEW_EXPENSES: "Informe suas despesas...",
        AgentState.INTERVIEW_DEPENDENTS: "Número de dependentes...",
        AgentState.INTERVIEW_DEBTS: "Tem dívidas? (sim/não)...",
        AgentState.INTERVIEW_CONFIRM: "Confirma? (sim/não)...",
    }

    user_input = st.chat_input(placeholder=placeholders.get(current_state, "Digite sua mensagem..."))
    if user_input:
        process_user_input(user_input)
        st.rerun()


def main():
    st.set_page_config(page_title="Banco Ágil - Chat com IA", page_icon="🏦", layout="centered", initial_sidebar_state="collapsed")

    apply_custom_css()
    init_session_state()
    render_header()

    if "api_health_checked" not in st.session_state:
        st.session_state.api_health_checked = True
        with st.spinner("Verificando conexão..."):
            api_client = APIClient()
            try:
                if asyncio.run(api_client.health_check()):
                    st.success("Sistema online!")
                    time.sleep(1)
                else:
                    st.error("Sistema indisponível")
                    st.info("Verifique se a API está rodando na porta 8000")
                    return
            except Exception as e:
                st.error(f"Erro: {e}")
                return

    if st.session_state.current_state == AgentState.WELCOME:
        handle_welcome()
        st.rerun()

    render_chat()
    render_input()

    with st.sidebar:
        st.markdown("### CPFs de Teste")
        st.markdown("**Maria Silva**\n- CPF: `12345678901`\n- Data: `15/05/1990`\n\n**João Santos**\n- CPF: `98765432100`\n- Data: `22/03/1985`\n\n**Ana Oliveira**\n- CPF: `11122233344`\n- Data: `08/11/1992`")
        st.divider()
        if st.button("Reiniciar"):
            reset_session()
            st.rerun()


if __name__ == "__main__":
    main()
