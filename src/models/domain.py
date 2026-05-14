from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Client:
    cpf: str
    name: str
    birthdate: date
    score: int
    current_limit: float


@dataclass(frozen=True)
class ScoreLimit:
    score_min: int
    score_max: int
    limit: float
