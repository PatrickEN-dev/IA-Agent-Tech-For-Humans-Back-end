"""Mede a acurácia do classificador de intenção sobre um conjunto rotulado.

Por que isto existe: a arquitetura híbrida afirma que as regras resolvem a maioria das
mensagens e o LLM só entra no que sobra. Isso é uma afirmação mensurável, e mensurá-la
é a diferença entre "usei um LLM" e ter engenharia em cima dele. O número que sai daqui
é o que sustenta o texto do README — e ele é medido, não estimado.

Uso:
    python scripts/eval_intents.py                  # só regras (não usa rede)
    python scripts/eval_intents.py --llm            # regras, LLM e híbrido
    python scripts/eval_intents.py --fail-under 80  # trava o CI abaixo da meta

Sem `--llm` o script não faz nenhuma chamada externa, então roda no CI.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.llm_service import VALID_INTENTS, LLMService  # noqa: E402

EVAL_FILE = Path(__file__).resolve().parent.parent / "evals" / "intents.jsonl"


@dataclass
class Case:
    text: str
    intent: str


@dataclass
class Result:
    name: str
    total: int = 0
    correct: int = 0
    # Casos em que o classificador não arriscou nenhum rótulo.
    abstained: int = 0
    confusion: Counter = field(default_factory=Counter)
    misses: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def coverage(self) -> float:
        """Fração de mensagens em que o classificador deu alguma resposta."""
        return (self.total - self.abstained) / self.total if self.total else 0.0

    def record(self, expected: str, predicted: str | None, text: str = "") -> None:
        self.total += 1
        if predicted is None:
            self.abstained += 1
            # Abster-se conta como acerto em "other": não classificar uma mensagem
            # sem sentido é o comportamento correto, e o orquestrador trata os dois
            # casos do mesmo jeito.
            if expected == "other":
                self.correct += 1
                return
            self.confusion[(expected, "—")] += 1
            self.misses.append((expected, "—", text))
            return

        if predicted == expected:
            self.correct += 1
        else:
            self.confusion[(expected, predicted)] += 1
            self.misses.append((expected, predicted, text))


def load_cases(path: Path) -> list[Case]:
    cases: list[Case] = []
    with open(path, encoding="utf-8") as f:
        for line_number, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            data = json.loads(raw)
            intent = data["intent"]
            if intent not in VALID_INTENTS:
                raise ValueError(f"linha {line_number}: rótulo desconhecido {intent!r}")
            cases.append(Case(text=data["text"], intent=intent))
    return cases


async def evaluate(cases: list[Case], use_llm: bool) -> list[Result]:
    service = LLMService()

    rules = Result("Regras (0 ms, sem rede)")
    for case in cases:
        rules.record(case.intent, service.classify_with_rules(case.text), case.text)

    results = [rules]

    if use_llm:
        llm_only = Result("LLM puro")
        hybrid = Result("Híbrido (regras, LLM no resto)")

        for case in cases:
            rule_intent = service.classify_with_rules(case.text)

            llm_intent = await service._classify_with_langchain(case.text)
            llm_only.record(case.intent, llm_intent, case.text)

            hybrid.record(case.intent, rule_intent or llm_intent, case.text)

        results.extend([llm_only, hybrid])

    return results


def print_result(result: Result, *, show_confusion: bool) -> None:
    print(f"\n{result.name}")
    print("-" * len(result.name))
    print(f"  acurácia:  {result.accuracy:6.1%}  ({result.correct}/{result.total})")
    print(f"  cobertura: {result.coverage:6.1%}  (abstenções: {result.abstained})")

    if not show_confusion or not result.confusion:
        return

    print("\n  erros mais frequentes (esperado -> previsto):")
    for (expected, predicted), count in result.confusion.most_common(10):
        print(f"    {expected:>16} -> {predicted:<16} {count}x")

    # As frases que erraram são o material de trabalho: sem elas o número diz que há
    # um problema, mas não o que consertar.
    print("\n  frases que erraram:")
    for expected, predicted, text in result.misses[:25]:
        print(f"    [{expected} -> {predicted}] {text!r}")


def print_per_label(cases: list[Case], result: Result) -> None:
    por_rotulo: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    erros_por_rotulo = Counter(expected for expected, _ in result.confusion.elements())

    for case in cases:
        por_rotulo[case.intent][1] += 1

    print("\n  por rótulo:")
    for intent in sorted(por_rotulo):
        total = por_rotulo[intent][1]
        erros = erros_por_rotulo.get(intent, 0)
        acertos = total - erros
        marca = " " if erros == 0 else "!"
        print(f"   {marca} {intent:>16}  {acertos:>3}/{total:<3}  {acertos / total:6.1%}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", action="store_true", help="também avalia LLM e híbrido")
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        metavar="PCT",
        help="sai com 1 se a acurácia das regras ficar abaixo deste valor",
    )
    parser.add_argument("--file", type=Path, default=EVAL_FILE)
    args = parser.parse_args()

    cases = load_cases(args.file)
    print(f"Avaliando {len(cases)} mensagens rotuladas de {args.file.name}")

    results = asyncio.run(evaluate(cases, args.llm))

    for result in results:
        print_result(result, show_confusion=True)

    print_per_label(cases, results[0])

    print("\nResumo")
    print("------")
    for result in results:
        print(f"  {result.name:<34} {result.accuracy:6.1%}")

    rules_accuracy = results[0].accuracy * 100
    if args.fail_under is not None and rules_accuracy < args.fail_under:
        print(
            f"\nFALHOU: acurácia das regras {rules_accuracy:.1f}% "
            f"abaixo do mínimo de {args.fail_under:.1f}%"
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
