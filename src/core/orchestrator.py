"""Conversation orchestrator.

Receives every chat message, picks the right agent based on session state +
intent, runs it, and wraps the technical reply in a friendly tone via the LLM.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException

from src.agents.base import Agent, AgentReply
from src.agents.credit import CreditAgent
from src.agents.exchange import ExchangeAgent
from src.agents.interview import InterviewAgent
from src.agents.triage import TriageAgent
from src.core.intents import (
    IntentRouter,
    is_accept,
    is_cancel,
    is_help,
    is_reject,
    is_smalltalk,
    menu_message,
)
from src.utils.extract import classify_intent_rule_based
from src.core.session import (
    AGENT_CREDIT,
    AGENT_EXCHANGE,
    AGENT_INTERVIEW,
    AGENT_TRIAGE,
    STATE_AUTHENTICATED,
    STATE_COLLECTING_BIRTHDATE,
    STATE_COLLECTING_CPF,
    STATE_CREDIT_INCREASE,
    STATE_EXCHANGE_FROM,
    STATE_EXCHANGE_TO,
    STATE_GOODBYE,
    STATE_INTERVIEW_DEBTS,
    STATE_INTERVIEW_DEPENDENTS,
    STATE_INTERVIEW_EMPLOYMENT,
    STATE_INTERVIEW_EXPENSES,
    STATE_INTERVIEW_INCOME,
    STATE_WELCOME,
    Session,
    SessionStore,
)
from src.models.schemas import ChatRequest, ChatResponse, RedirectAction
from src.services.llm import LLMGateway

logger = logging.getLogger(__name__)


_TRIAGE_STATES = {STATE_WELCOME, STATE_COLLECTING_CPF, STATE_COLLECTING_BIRTHDATE}
_INTERVIEW_STATES = {
    STATE_INTERVIEW_INCOME,
    STATE_INTERVIEW_EMPLOYMENT,
    STATE_INTERVIEW_EXPENSES,
    STATE_INTERVIEW_DEPENDENTS,
    STATE_INTERVIEW_DEBTS,
}
_EXCHANGE_STATES = {STATE_EXCHANGE_FROM, STATE_EXCHANGE_TO}
_CREDIT_STATES = {STATE_CREDIT_INCREASE}


class Orchestrator:
    def __init__(
        self,
        *,
        triage: TriageAgent | None = None,
        credit: CreditAgent | None = None,
        interview: InterviewAgent | None = None,
        exchange: ExchangeAgent | None = None,
        llm: LLMGateway | None = None,
        sessions: SessionStore | None = None,
    ) -> None:
        self._llm = llm or LLMGateway()
        self._sessions = sessions or SessionStore()
        self._agents: dict[str, Agent] = {
            AGENT_TRIAGE: triage or TriageAgent(),
            AGENT_CREDIT: credit or CreditAgent(),
            AGENT_INTERVIEW: interview or InterviewAgent(),
            AGENT_EXCHANGE: exchange or ExchangeAgent(),
        }
        self._router = IntentRouter(self._llm)

    def agent(self, name: str) -> Agent:
        """Public accessor so routes/tests don't reach into private attrs."""
        return self._agents[name]

    async def init_session(self) -> ChatResponse:
        session_id, session = self._sessions.create()
        session.state = STATE_COLLECTING_CPF
        from src.agents.triage import WELCOME_MESSAGE

        return self._build_response(session_id, session, WELCOME_MESSAGE)

    async def process(self, request: ChatRequest) -> ChatResponse:
        request_id = uuid.uuid4().hex[:8]
        session_id, session = self._sessions.get_or_create(request.session_id)
        message = request.message.strip()
        if not message:
            return self._build_response(
                session_id, session,
                "Não recebi nenhuma mensagem. Pode escrever novamente?",
            )

        # After saying goodbye, treat the next message as a brand-new session
        # for the same id — avoids the user being stuck in 'goodbye' forever.
        if session.state == STATE_GOODBYE:
            session.reset_active_flow()
            session.token = None
            session.cpf = None
            session.birthdate = None
            session.user_name = None
            session.history = []
            session.state = STATE_COLLECTING_CPF
            session.current_agent = AGENT_TRIAGE

        session.record("user", message)
        logger.info(
            "[req=%s] dispatch state=%s agent=%s auth=%s",
            request_id, session.state, session.current_agent, session.authenticated,
        )

        try:
            reply = await self._dispatch(session, message)
        except HTTPException as exc:
            logger.warning("[req=%s] downstream HTTPException: %s", request_id, exc.detail)
            reply = AgentReply(text=_friendly_error_message(exc), humanize=False)
        except Exception:
            logger.exception("[req=%s] unexpected error in dispatch", request_id)
            reply = AgentReply(
                text="Tive um problema técnico aqui. Pode tentar novamente em instantes?",
                humanize=False,
            )

        self._apply(session, reply)

        text = reply.text
        if reply.humanize:
            text = await self._llm.compose_reply(
                user_message=message,
                technical_answer=reply.text,
                history=session.history,
                user_name=session.user_name,
            )
        session.record("assistant", text)
        return self._build_response(session_id, session, text)

    async def _dispatch(self, session: Session, message: str) -> AgentReply:
        # Exit works at any state — before or after authentication.
        if classify_intent_rule_based(message) == "exit":
            return AgentReply(
                text="Obrigado por usar o Banco Ágil. Até a próxima!",
                next_state=STATE_GOODBYE,
                humanize=False,
            )

        if not session.authenticated:
            return await self._agents[AGENT_TRIAGE].handle(session, message)

        # 1) Pending redirect (e.g. "want to start the interview?")
        if session.pending_redirect:
            if is_accept(message):
                return await self._consume_redirect(session)
            if is_reject(message):
                session.pending_redirect = None
                return AgentReply(text="Tudo bem, sem problema. " + menu_message())

        # 2) Mid-flow: stay in the active agent
        active = self._active_agent_for(session.state)
        if active is not None:
            # Meta-commands let the user bail out of a flow without being
            # forced to keep answering questions.
            if is_cancel(message):
                session.reset_active_flow()
                return AgentReply(
                    text="Beleza, cancelei. " + menu_message(),
                    next_state=STATE_AUTHENTICATED if session.authenticated else STATE_COLLECTING_CPF,
                    humanize=False,
                )
            if is_help(message):
                return AgentReply(
                    text=menu_message() + " (Se quiser sair desse passo, diga 'cancelar'.)",
                    humanize=False,
                )

            # Did the user pivot to a different banking topic mid-flow?
            # Ask for confirmation instead of silently dropping the request.
            switch = _detect_mid_flow_intent_switch(session, message)
            if switch is not None:
                session.pending_redirect = {
                    "target_agent": switch,
                    "reason": "mid_flow_switch",
                }
                return AgentReply(
                    text=(
                        f"Notei que você quer falar sobre {_label_for(switch)}. "
                        "Quer interromper o que estamos fazendo e ir pra lá? "
                        "(sim/não)"
                    ),
                    humanize=False,
                )

            if is_smalltalk(message):
                return AgentReply(
                    text=f"Oi! Estamos no meio de um atendimento. "
                         f"Para continuar, " + self._resume_hint(session),
                    humanize=False,
                )
            return await self._agents[active].handle(session, message)

        # 3) At rest: classify intent and route
        intent, target_agent = await self._router.route(message)
        if intent == "exit":
            return AgentReply(
                text="Obrigado por usar o Banco Ágil. Até a próxima!",
                next_state=STATE_GOODBYE,
                humanize=False,
            )
        if target_agent is None:
            return AgentReply(text=menu_message(), humanize=False)

        session.current_agent = target_agent
        if intent == "request_increase":
            return await self._agents[AGENT_CREDIT].handle(
                self._with_state(session, STATE_CREDIT_INCREASE),
                message,
            )
        return await self._agents[target_agent].handle(session, message)

    async def _consume_redirect(self, session: Session) -> AgentReply:
        redirect = session.pending_redirect or {}
        session.pending_redirect = None
        target = redirect.get("target_agent")
        reason = redirect.get("reason")

        # Mid-flow switch: drop the current flow before entering the new one,
        # otherwise the new agent would inherit stale state.
        if reason == "mid_flow_switch" and target in self._agents:
            session.reset_active_flow()
            session.current_agent = target
            return await self._agents[target].handle(session, "")

        if target == "interview":
            session.current_agent = AGENT_INTERVIEW
            return await self._agents[AGENT_INTERVIEW].handle(session, "")
        if target == "credit":
            session.current_agent = AGENT_CREDIT
            return await self._agents[AGENT_CREDIT].handle(session, "")
        if target == "credit_increase":
            session.current_agent = AGENT_CREDIT
            return await self._agents[AGENT_CREDIT].handle(
                self._with_state(session, STATE_CREDIT_INCREASE),
                "",
            )
        return AgentReply(text=menu_message(), humanize=False)

    def _apply(self, session: Session, reply: AgentReply) -> None:
        if reply.next_state is not None:
            session.state = reply.next_state
        if reply.next_agent is not None:
            session.current_agent = reply.next_agent
        if reply.redirect is not None:
            session.pending_redirect = reply.redirect

    def _with_state(self, session: Session, state: str) -> Session:
        session.state = state
        return session

    def _resume_hint(self, session: Session) -> str:
        hints = {
            STATE_COLLECTING_CPF: "informe seu CPF (11 dígitos).",
            STATE_COLLECTING_BIRTHDATE: "informe sua data de nascimento (DD/MM/AAAA).",
            STATE_CREDIT_INCREASE: "diga o valor do novo limite desejado.",
            STATE_INTERVIEW_INCOME: "diga sua renda mensal.",
            STATE_INTERVIEW_EMPLOYMENT: "informe seu tipo de trabalho (CLT, MEI, etc).",
            STATE_INTERVIEW_EXPENSES: "diga suas despesas mensais.",
            STATE_INTERVIEW_DEPENDENTS: "diga quantos dependentes você tem.",
            STATE_INTERVIEW_DEBTS: "responda se tem dívidas (sim/não).",
            STATE_EXCHANGE_FROM: "qual moeda você quer converter?",
            STATE_EXCHANGE_TO: "para qual moeda você quer converter?",
        }
        return hints.get(session.state, "responda a última pergunta.")

    def _active_agent_for(self, state: str) -> str | None:
        if state in _TRIAGE_STATES:
            return AGENT_TRIAGE
        if state in _INTERVIEW_STATES:
            return AGENT_INTERVIEW
        if state in _EXCHANGE_STATES:
            return AGENT_EXCHANGE
        if state in _CREDIT_STATES:
            return AGENT_CREDIT
        return None

    def _build_response(
        self,
        session_id: str,
        session: Session,
        message: str,
    ) -> ChatResponse:
        redirect_action = None
        if session.pending_redirect:
            redirect_action = RedirectAction(
                should_redirect=True,
                target_agent=session.pending_redirect.get("target_agent"),
                reason=session.pending_redirect.get("reason"),
                suggested_action=session.pending_redirect.get("suggested_action"),
            )
        return ChatResponse(
            session_id=session_id,
            message=message,
            state=session.state,
            current_agent=session.current_agent,
            authenticated=session.authenticated,
            token=session.token,
            available_actions=_available_actions(session),
            redirect_suggestion=redirect_action,
        )


def _available_actions(session: Session) -> list[str]:
    if not session.authenticated:
        return ["authenticate"]
    return ["credit_limit", "request_increase", "exchange_rate", "interview"]


_INTENT_TO_AGENT_LOCAL: dict[str, str] = {
    "credit_limit": AGENT_CREDIT,
    "request_increase": AGENT_CREDIT,
    "interview": AGENT_INTERVIEW,
    "exchange_rate": AGENT_EXCHANGE,
}

_AGENT_LABELS: dict[str, str] = {
    AGENT_CREDIT: "limite de crédito",
    AGENT_INTERVIEW: "atualizar seu perfil",
    AGENT_EXCHANGE: "cotação de moedas",
}


def _label_for(agent: str) -> str:
    return _AGENT_LABELS.get(agent, "outro assunto")


def _detect_mid_flow_intent_switch(session: Session, message: str) -> str | None:
    """Return the agent name the user is trying to switch to, or None.

    Only fires when the rule-based classifier identifies a banking intent
    AND it points to a *different* agent than the one currently in charge.
    Bare numbers/dates that don't match any keyword stay with the active
    agent (so "5000" during interview is treated as renda, not a switch).
    """
    intent = classify_intent_rule_based(message)
    if intent in ("unknown", "exit"):
        return None
    target = _INTENT_TO_AGENT_LOCAL.get(intent)
    if target is None or target == session.current_agent:
        return None
    return target


def _friendly_error_message(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        msg = str(detail.get("message", ""))
        if "Maximum authentication" in msg:
            return (
                "Você atingiu o limite de tentativas de autenticação. "
                "Por segurança, tente novamente daqui a pouco."
            )
        if "Invalid CPF" in msg or "birthdate" in msg.lower():
            return "Não consegui validar seus dados. Vamos tentar de novo?"
    if exc.status_code == 404:
        return "Não encontrei esse dado. Pode conferir e tentar de novo?"
    return "Tive um problema ao processar isso. Tente novamente, por favor."
