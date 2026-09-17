"""Contadores de uso da conversa.

O número que interessa é a fração de turnos que precisou chamar o modelo. Ele é o que
sustenta a afirmação de custo da arquitetura híbrida — e é melhor medi-lo do que
estimá-lo, porque a estimativa envelhece a cada regra nova de classificação.

Vive em memória e zera no restart: é métrica de demonstração, não faturamento. Em
produção isso seria um contador Prometheus, com a mesma chamada no mesmo lugar.
"""

import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Telemetry:
    turns_total: int = 0
    llm_turns_total: int = 0
    llm_ms_total: float = 0.0
    turn_ms_total: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_turn(self, *, used_llm: bool, turn_ms: float, llm_ms: float = 0.0) -> None:
        with self._lock:
            self.turns_total += 1
            self.turn_ms_total += turn_ms
            if used_llm:
                self.llm_turns_total += 1
                self.llm_ms_total += llm_ms

    def snapshot(self) -> dict:
        with self._lock:
            turns = self.turns_total
            llm_turns = self.llm_turns_total
            return {
                "turns_total": turns,
                "llm_turns_total": llm_turns,
                "llm_turn_ratio": round(llm_turns / turns, 4) if turns else 0.0,
                "avg_turn_ms": round(self.turn_ms_total / turns, 1) if turns else 0.0,
                "avg_llm_ms": round(self.llm_ms_total / llm_turns, 1) if llm_turns else 0.0,
            }

    def reset(self) -> None:
        with self._lock:
            self.turns_total = 0
            self.llm_turns_total = 0
            self.llm_ms_total = 0.0
            self.turn_ms_total = 0.0


telemetry = Telemetry()
