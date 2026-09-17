"""Política de crédito: teto por score, decisão de aumento e recálculo por entrevista.

Toda a regra de negócio numérica vive aqui, fora dos agentes e longe do LLM. O modelo
nunca decide limite nem score; ele só reescreve em linguagem natural um texto que já
saiu daqui pronto.
"""

import logging
from dataclasses import dataclass
from typing import Literal

from src.db.repositories import ScoreLimitRepository

logger = logging.getLogger(__name__)

LimitDecision = Literal["approved", "pending_analysis", "denied"]

# Faixa acima do teto em que o pedido não é negado de imediato, e sim encaminhado
# para análise manual — desde que o score já demonstre histórico.
MANUAL_REVIEW_MULTIPLIER = 1.5
MANUAL_REVIEW_MIN_SCORE = 600

# Fallback usado apenas se a tabela de faixas estiver vazia (banco sem seed).
FALLBACK_MIN_LIMIT = 500.0
FALLBACK_MAX_LIMIT = 50000.0

PESO_RENDA = 30

PESO_EMPREGO: dict[str, int] = {
    "FORMAL": 300,
    "CLT": 300,
    "PUBLICO": 300,
    "AUTONOMO": 200,
    "MEI": 200,
    "DESEMPREGADO": 0,
}

PESO_DEPENDENTES: dict[int, int] = {
    0: 100,
    1: 80,
    2: 60,
    3: 30,
}

PESO_DIVIDAS: dict[bool, int] = {
    True: -100,
    False: 100,
}

# Quanto o histórico do cliente pesa contra a foto tirada na entrevista.
# Média cega (0.5/0.5) punia demais quem já tinha score alto e premiava demais quem
# respondia bem uma vez só.
PESO_SCORE_ATUAL = 0.6
PESO_SCORE_ENTREVISTA = 0.4

EMPREGO_LABEL = {
    "CLT": "vínculo CLT",
    "FORMAL": "vínculo formal",
    "PUBLICO": "servidor público",
    "AUTONOMO": "trabalho autônomo",
    "MEI": "MEI",
    "DESEMPREGADO": "sem vínculo empregatício no momento",
}


@dataclass
class ScoreBreakdown:
    """Resultado da entrevista com a contribuição de cada fator, para poder explicar."""

    score_calculado: int
    componentes: dict[str, float]

    def principais_fatores(self, quantidade: int = 2) -> list[tuple[str, float]]:
        """Fatores de maior peso absoluto, do mais relevante para o menos."""
        return sorted(
            self.componentes.items(), key=lambda item: abs(item[1]), reverse=True
        )[:quantidade]


@dataclass
class LimitEvaluation:
    decision: LimitDecision
    ceiling: float
    motivo: str


class ScoreService:
    def __init__(self, score_limit_repository: ScoreLimitRepository | None = None) -> None:
        self._limits = score_limit_repository or ScoreLimitRepository()

    async def get_limit_for_score(self, score: int) -> float:
        """Teto de limite que o score sustenta, pela tabela de faixas."""
        limite = await self._limits.limit_for_score(score)
        if limite is not None:
            return limite

        logger.warning("Tabela de faixas nao cobre o score %s; usando fallback", score)
        if score >= 900:
            return FALLBACK_MAX_LIMIT
        return FALLBACK_MIN_LIMIT

    async def evaluate_limit_request(
        self, score: int, current_limit: float, requested_limit: float
    ) -> LimitEvaluation:
        """Decide um pedido de aumento e devolve o motivo legível da decisão.

        Três desfechos possíveis, e os três acontecem de verdade:
        - até o teto do score: aprovado na hora;
        - entre o teto e 1,5x o teto, com score >= 600: análise manual;
        - acima disso: negado, com oferta de entrevista para reavaliar o score.
        """
        ceiling = await self.get_limit_for_score(score)

        if requested_limit <= current_limit:
            return LimitEvaluation(
                decision="approved",
                ceiling=ceiling,
                motivo="Valor já coberto pelo limite atual",
            )

        if requested_limit <= ceiling:
            return LimitEvaluation(
                decision="approved",
                ceiling=ceiling,
                motivo=f"Dentro do teto de {ceiling:.2f} para o score {score}",
            )

        if (
            score >= MANUAL_REVIEW_MIN_SCORE
            and requested_limit <= ceiling * MANUAL_REVIEW_MULTIPLIER
        ):
            return LimitEvaluation(
                decision="pending_analysis",
                ceiling=ceiling,
                motivo=(
                    f"Até {MANUAL_REVIEW_MULTIPLIER:g}x o teto ({ceiling:.2f}) "
                    f"com score {score}: encaminhado para análise manual"
                ),
            )

        return LimitEvaluation(
            decision="denied",
            ceiling=ceiling,
            motivo=f"Acima do teto de {ceiling:.2f} sustentado pelo score {score}",
        )

    def calculate_interview_score(
        self,
        renda_mensal: float,
        tipo_emprego: str,
        despesas: float,
        num_dependentes: int,
        tem_dividas: bool,
    ) -> ScoreBreakdown:
        """Score sugerido pela entrevista, com a contribuição de cada fator separada."""
        componente_renda = (renda_mensal / (despesas + 1)) * PESO_RENDA
        # Sem o teto, uma renda declarada de R$ 1.000.000 com R$ 0 de despesa
        # estouraria todos os outros fatores sozinha.
        componente_renda = min(componente_renda, 400.0)

        tipo_emprego_upper = tipo_emprego.upper()
        componente_emprego = float(PESO_EMPREGO.get(tipo_emprego_upper, 0))
        componente_dependentes = float(
            PESO_DEPENDENTES.get(min(num_dependentes, 3), 30)
        )
        componente_dividas = float(PESO_DIVIDAS.get(tem_dividas, 0))

        total = (
            componente_renda
            + componente_emprego
            + componente_dependentes
            + componente_dividas
        )

        return ScoreBreakdown(
            score_calculado=max(0, min(1000, int(total))),
            componentes={
                "renda_vs_despesas": round(componente_renda, 1),
                "tipo_de_emprego": componente_emprego,
                "dependentes": componente_dependentes,
                "dividas": componente_dividas,
            },
        )

    @staticmethod
    def blend_scores(current_score: int, interview_score: int) -> int:
        """Combina histórico e entrevista com pesos fixos, em vez de média cega."""
        blended = PESO_SCORE_ATUAL * current_score + PESO_SCORE_ENTREVISTA * interview_score
        return max(0, min(1000, round(blended)))

    @staticmethod
    def explain_factors(breakdown: ScoreBreakdown, tipo_emprego: str) -> str:
        """Frase curta dizendo o que mais pesou, para a resposta do chat."""
        labels = {
            "renda_vs_despesas": "a relação entre sua renda e suas despesas",
            "tipo_de_emprego": f"seu {EMPREGO_LABEL.get(tipo_emprego.upper(), 'vínculo de trabalho')}",
            "dependentes": "o número de dependentes",
            "dividas": "suas dívidas em aberto",
        }
        partes = []
        for nome, valor in breakdown.principais_fatores(2):
            sinal = "contribuiu" if valor >= 0 else "pesou contra"
            partes.append(f"{labels.get(nome, nome)} {sinal}")
        if not partes:
            return ""
        return "O que mais influenciou: " + " e ".join(partes) + "."
