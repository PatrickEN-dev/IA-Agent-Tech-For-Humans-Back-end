"""Scoring rules for credit decisions.

Mostly pure functions. The only I/O is reading the score→limit ranges from
the repository, which is cached in-memory with a short TTL so we don't hit
the CSV on every request.
"""
from __future__ import annotations

import time
from typing import Final

from src.models.domain import ScoreLimit
from src.models.schemas import EmploymentType, LimitStatus
from src.services.clients import ClientRepository

_AVAILABLE_FRACTION: Final[float] = 0.8

_EMPLOYMENT_WEIGHT: Final[dict[EmploymentType, int]] = {
    "FORMAL": 300,
    "CLT": 300,
    "PUBLICO": 300,
    "AUTONOMO": 200,
    "MEI": 200,
    "DESEMPREGADO": 0,
}

_DEPENDENT_WEIGHT: Final[dict[int, int]] = {0: 100, 1: 80, 2: 60, 3: 30}
_DEBT_WEIGHT: Final[dict[bool, int]] = {True: -100, False: 100}
_INCOME_WEIGHT: Final[int] = 30

_DEFAULT_LIMITS: Final[tuple[tuple[int, int, float], ...]] = (
    (0, 299, 500.0),
    (300, 399, 1000.0),
    (400, 499, 3000.0),
    (500, 599, 5000.0),
    (600, 699, 8000.0),
    (700, 799, 15000.0),
    (800, 899, 25000.0),
    (900, 1000, 50000.0),
)


_LIMITS_TTL_SECONDS: Final[float] = 60.0


class ScoringService:
    def __init__(self, clients: ClientRepository | None = None) -> None:
        self._clients = clients or ClientRepository()
        self._cached_limits: list[ScoreLimit] | None = None
        self._cached_at: float = 0.0

    async def limit_for_score(self, score: int) -> float:
        for rng in await self._score_ranges():
            if rng.score_min <= score <= rng.score_max:
                return rng.limit
        # CSV missing or score out of range -> built-in fallback
        for low, high, limit in _DEFAULT_LIMITS:
            if low <= score <= high:
                return limit
        return 1000.0

    async def _score_ranges(self) -> list[ScoreLimit]:
        now = time.monotonic()
        if self._cached_limits is None or (now - self._cached_at) > _LIMITS_TTL_SECONDS:
            self._cached_limits = await self._clients.read_score_limits()
            self._cached_at = now
        return self._cached_limits

    def invalidate_cache(self) -> None:
        """Public hook for tests that mutate the underlying CSV."""
        self._cached_limits = None
        self._cached_at = 0.0

    def available_from(self, current_limit: float) -> float:
        return round(current_limit * _AVAILABLE_FRACTION, 2)

    async def evaluate_request(
        self, score: int, current_limit: float, requested_limit: float
    ) -> LimitStatus:
        if requested_limit <= current_limit:
            return "approved"
        max_for_score = await self.limit_for_score(score)
        if requested_limit <= max_for_score:
            return "approved"
        if requested_limit <= max_for_score * 1.5:
            return "pending_analysis"
        return "denied"

    def compute_interview_score(
        self,
        *,
        renda_mensal: float,
        tipo_emprego: EmploymentType,
        despesas: float,
        num_dependentes: int,
        tem_dividas: bool,
    ) -> int:
        income_component = (renda_mensal / (despesas + 1)) * _INCOME_WEIGHT
        employment_component = _EMPLOYMENT_WEIGHT.get(tipo_emprego, 0)
        dependent_component = _DEPENDENT_WEIGHT.get(min(num_dependentes, 3), 30)
        debt_component = _DEBT_WEIGHT[tem_dividas]
        total = (
            income_component
            + employment_component
            + dependent_component
            + debt_component
        )
        return max(0, min(1000, int(total)))

    def blend_with_history(self, previous_score: int, new_score: int) -> int:
        """Average current and previous score so updates are smoothed."""
        return max(0, min(1000, (previous_score + new_score) // 2))

    @staticmethod
    def recommendation_for(score: int) -> str:
        if score >= 800:
            return "Perfil excelente — você se qualifica para crédito premium."
        if score >= 600:
            return "Bom perfil — acesso aos produtos de crédito padrão."
        if score >= 400:
            return "Perfil moderado — reduzir despesas ajuda a melhorar seu score."
        return "Perfil em recuperação — recomendamos uma consultoria financeira."
