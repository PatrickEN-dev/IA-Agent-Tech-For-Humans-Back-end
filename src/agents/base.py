"""Shared agent contract.

Every concrete agent (Triage / Credit / Interview / Exchange) returns an
`AgentReply` from its `handle` method. The orchestrator consumes the reply,
updates the session and optionally humanizes the message before sending it
back to the API.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

from src.core.session import Session


@dataclass
class AgentReply:
    text: str
    next_state: str | None = None
    next_agent: str | None = None
    redirect: dict[str, str] | None = None
    humanize: bool = True


class Agent(ABC):
    """Base class for a banking agent.

    Concrete agents override `handle`. The orchestrator never inspects them
    beyond this contract.
    """

    name: str

    @abstractmethod
    async def handle(self, session: Session, message: str) -> AgentReply:
        ...


class SupportsHandoff(Protocol):
    """Marker protocol for agents that can declare their next state cleanly.

    Useful in type hints; not currently used at runtime — kept here as a hint
    to future maintainers that handoffs are part of the contract.
    """

    async def handle(self, session: Session, message: str) -> AgentReply: ...
