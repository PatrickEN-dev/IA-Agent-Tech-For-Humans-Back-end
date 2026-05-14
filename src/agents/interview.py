"""Interview agent — collects income/expenses/debts to update the score."""
from __future__ import annotations

import logging

from src.agents.base import Agent, AgentReply
from src.core.session import (
    AGENT_INTERVIEW,
    STATE_AUTHENTICATED,
    STATE_INTERVIEW_DEBTS,
    STATE_INTERVIEW_DEPENDENTS,
    STATE_INTERVIEW_EMPLOYMENT,
    STATE_INTERVIEW_EXPENSES,
    STATE_INTERVIEW_INCOME,
    Session,
)
from src.models.schemas import InterviewRequest, InterviewResponse
from src.services.clients import ClientRepository
from src.services.scoring import ScoringService
from src.utils.exceptions import ClientNotFoundError
from src.utils.extract import (
    extract_employment,
    extract_integer,
    extract_money,
    parse_boolean,
)

logger = logging.getLogger(__name__)

_QUESTIONS: dict[str, str] = {
    STATE_INTERVIEW_INCOME: (
        "Vamos atualizar seu perfil para reavaliar o score. Qual é a sua "
        "renda mensal aproximada?"
    ),
    STATE_INTERVIEW_EMPLOYMENT: (
        "Qual é o seu tipo de trabalho? CLT, servidor público, autônomo, "
        "MEI ou desempregado?"
    ),
    STATE_INTERVIEW_EXPENSES: "Quanto você gasta por mês, aproximadamente?",
    STATE_INTERVIEW_DEPENDENTS: (
        "Quantas pessoas dependem financeiramente de você hoje? "
        "Se ninguém, pode dizer zero."
    ),
    STATE_INTERVIEW_DEBTS: "Você tem alguma dívida em aberto? (sim/não)",
}


class InterviewAgent(Agent):
    name = AGENT_INTERVIEW

    def __init__(
        self,
        clients: ClientRepository | None = None,
        scoring: ScoringService | None = None,
    ) -> None:
        self._clients = clients or ClientRepository()
        self._scoring = scoring or ScoringService(self._clients)

    async def submit(self, cpf: str, request: InterviewRequest) -> InterviewResponse:
        client = await self._clients.get_by_cpf(cpf)
        if client is None:
            raise ClientNotFoundError(cpf)

        new_score_raw = self._scoring.compute_interview_score(
            renda_mensal=request.renda_mensal,
            tipo_emprego=request.tipo_emprego,
            despesas=request.despesas,
            num_dependentes=request.num_dependentes,
            tem_dividas=request.tem_dividas,
        )
        final_score = self._scoring.blend_with_history(client.score, new_score_raw)
        await self._clients.update_score(cpf, final_score)

        return InterviewResponse(
            cpf=cpf,
            previous_score=client.score,
            new_score=final_score,
            recommendation=self._scoring.recommendation_for(final_score),
            redirect_to="/credit/limit",
        )

    async def handle(self, session: Session, message: str) -> AgentReply:
        if session.state == STATE_AUTHENTICATED:
            session.collected = {}
            return AgentReply(
                text=_QUESTIONS[STATE_INTERVIEW_INCOME],
                next_state=STATE_INTERVIEW_INCOME,
            )

        if session.state == STATE_INTERVIEW_INCOME:
            return self._collect_money(session, message, "renda_mensal",
                                       next_state=STATE_INTERVIEW_EMPLOYMENT,
                                       retry_question=_QUESTIONS[STATE_INTERVIEW_INCOME])

        if session.state == STATE_INTERVIEW_EMPLOYMENT:
            employment = extract_employment(message)
            if employment is None:
                return AgentReply(
                    text=_QUESTIONS[STATE_INTERVIEW_EMPLOYMENT]
                    + " (Se preferir parar, é só dizer 'cancelar'.)",
                    next_state=STATE_INTERVIEW_EMPLOYMENT,
                    humanize=False,
                )
            session.collected["tipo_emprego"] = employment
            return AgentReply(
                text=_QUESTIONS[STATE_INTERVIEW_EXPENSES],
                next_state=STATE_INTERVIEW_EXPENSES,
            )

        if session.state == STATE_INTERVIEW_EXPENSES:
            return self._collect_money(session, message, "despesas",
                                       next_state=STATE_INTERVIEW_DEPENDENTS,
                                       retry_question=_QUESTIONS[STATE_INTERVIEW_EXPENSES])

        if session.state == STATE_INTERVIEW_DEPENDENTS:
            dependents = extract_integer(message)
            if dependents is None or dependents < 0:
                return AgentReply(
                    text=_QUESTIONS[STATE_INTERVIEW_DEPENDENTS]
                    + " (Se quiser sair, diga 'cancelar'.)",
                    next_state=STATE_INTERVIEW_DEPENDENTS,
                    humanize=False,
                )
            session.collected["num_dependentes"] = dependents
            return AgentReply(
                text=_QUESTIONS[STATE_INTERVIEW_DEBTS],
                next_state=STATE_INTERVIEW_DEBTS,
            )

        if session.state == STATE_INTERVIEW_DEBTS:
            has_debts = parse_boolean(message)
            if has_debts is None:
                return AgentReply(
                    text="Pode responder com sim ou não. "
                    + _QUESTIONS[STATE_INTERVIEW_DEBTS]
                    + " (Ou diga 'cancelar' para sair.)",
                    next_state=STATE_INTERVIEW_DEBTS,
                    humanize=False,
                )
            session.collected["tem_dividas"] = has_debts
            return await self._finalize(session)

        return AgentReply(
            text=_QUESTIONS[STATE_INTERVIEW_INCOME],
            next_state=STATE_INTERVIEW_INCOME,
        )

    def _collect_money(
        self,
        session: Session,
        message: str,
        key: str,
        *,
        next_state: str,
        retry_question: str,
    ) -> AgentReply:
        value = extract_money(message)
        if value is None or value < 0:
            return AgentReply(
                text=retry_question + " (Ou diga 'cancelar' para sair.)",
                next_state=session.state,
                humanize=False,
            )
        session.collected[key] = value
        return AgentReply(text=_QUESTIONS[next_state], next_state=next_state)

    async def _finalize(self, session: Session) -> AgentReply:
        assert session.cpf is not None
        request = InterviewRequest(
            renda_mensal=session.collected["renda_mensal"],
            tipo_emprego=session.collected["tipo_emprego"],
            despesas=session.collected["despesas"],
            num_dependentes=session.collected["num_dependentes"],
            tem_dividas=session.collected["tem_dividas"],
        )
        result = await self.submit(session.cpf, request)
        session.collected = {}
        session.pending_redirect = {
            "target_agent": "credit",
            "reason": "interview_completed",
        }
        text = (
            f"Entrevista concluída. Score anterior: {result.previous_score}. "
            f"Novo score: {result.new_score}. {result.recommendation} "
            "Quer consultar seu novo limite?"
        )
        return AgentReply(
            text=text,
            next_state=STATE_AUTHENTICATED,
            redirect=session.pending_redirect,
        )
