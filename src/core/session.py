"""Conversational session state.

A `Session` is the single mutable object passed around between the
orchestrator and the agents. Keep its surface small — every new field is a
new place where state can drift.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any


# Conversation phases. Strings (not enum) so they serialize trivially to JSON.
STATE_WELCOME = "welcome"
STATE_COLLECTING_CPF = "collecting_cpf"
STATE_COLLECTING_BIRTHDATE = "collecting_birthdate"
STATE_AUTHENTICATED = "authenticated"
STATE_CREDIT_INCREASE = "credit_increase_flow"
STATE_INTERVIEW_INCOME = "interview_income"
STATE_INTERVIEW_EMPLOYMENT = "interview_employment"
STATE_INTERVIEW_EXPENSES = "interview_expenses"
STATE_INTERVIEW_DEPENDENTS = "interview_dependents"
STATE_INTERVIEW_DEBTS = "interview_debts"
STATE_EXCHANGE_FROM = "exchange_from"
STATE_EXCHANGE_TO = "exchange_to"
STATE_GOODBYE = "goodbye"


AGENT_TRIAGE = "triage"
AGENT_CREDIT = "credit"
AGENT_INTERVIEW = "interview"
AGENT_EXCHANGE = "exchange"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Session:
    state: str = STATE_WELCOME
    current_agent: str = AGENT_TRIAGE
    cpf: str | None = None
    birthdate: date | None = None
    token: str | None = None
    user_name: str | None = None
    collected: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)
    pending_redirect: dict[str, str] | None = None
    created_at: datetime = field(default_factory=_now)
    last_activity_at: datetime = field(default_factory=_now)

    @property
    def authenticated(self) -> bool:
        return self.token is not None

    def touch(self) -> None:
        self.last_activity_at = _now()

    def reset_active_flow(self) -> None:
        """Clear in-progress flow state without dropping authentication."""
        self.collected = {}
        self.pending_redirect = None
        self.state = STATE_AUTHENTICATED if self.authenticated else STATE_COLLECTING_CPF

    def record(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        # Keep history bounded — long histories blow up LLM cost.
        if len(self.history) > 20:
            self.history = self.history[-20:]


class SessionStore:
    """In-memory session store with TTL.

    Swap for Redis later by implementing the same two methods. A session
    older than `ttl` is treated as expired: the next access creates a new
    one and the stale entry is dropped.
    """

    DEFAULT_TTL = timedelta(minutes=30)
    _MAX_SESSIONS = 10_000  # safety cap; production must move to Redis

    def __init__(self, ttl: timedelta | None = None) -> None:
        self._sessions: dict[str, Session] = {}
        self._ttl = ttl or self.DEFAULT_TTL

    def create(self) -> tuple[str, Session]:
        self._evict_expired()
        session_id = str(uuid.uuid4())
        session = Session()
        self._sessions[session_id] = session
        return session_id, session

    def get_or_create(self, session_id: str | None) -> tuple[str, Session]:
        if session_id and (session := self._sessions.get(session_id)):
            if not self._expired(session):
                session.touch()
                return session_id, session
            self._sessions.pop(session_id, None)
        return self.create()

    def clear(self) -> None:
        self._sessions.clear()

    def _expired(self, session: Session) -> bool:
        return (_now() - session.last_activity_at) > self._ttl

    def _evict_expired(self) -> None:
        expired = [sid for sid, s in self._sessions.items() if self._expired(s)]
        for sid in expired:
            self._sessions.pop(sid, None)
        # Hard cap: drop the oldest if we're past the safety ceiling.
        if len(self._sessions) > self._MAX_SESSIONS:
            oldest = sorted(self._sessions.items(), key=lambda kv: kv[1].last_activity_at)
            for sid, _ in oldest[: len(self._sessions) - self._MAX_SESSIONS]:
                self._sessions.pop(sid, None)
