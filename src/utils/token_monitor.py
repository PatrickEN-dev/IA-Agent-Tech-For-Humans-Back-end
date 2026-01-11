import json
import logging
from datetime import date
from typing import Dict, Any

logger = logging.getLogger(__name__)


class TokenMonitor:
    def __init__(self):
        self.usage_file = "token_usage.json"
        self.daily_usage = self._load_usage()

        self.costs = {
            "gpt-3.5-turbo": {
                "input": 0.0005,
                "output": 0.0015,
            },
            "gpt-4": {
                "input": 0.03,
                "output": 0.06,
            },
        }

    def _load_usage(self) -> Dict[str, Any]:
        """Carrega dados de uso do arquivo"""
        try:
            with open(self.usage_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "total_spent": 0.0,
                "daily": {},
                "sessions": 0,
                "ai_calls": 0,
                "cache_hits": 0,
            }

    def _save_usage(self):
        """Salva dados de uso no arquivo"""
        try:
            with open(self.usage_file, "w") as f:
                json.dump(self.daily_usage, f, indent=2)
        except Exception as e:
            logger.error(f"Erro ao salvar uso: {e}")

    def track_ai_call(
        self,
        model: str = "gpt-3.5-turbo",
        input_tokens: int = 0,
        output_tokens: int = 0,
    ):
        """Registra uso de tokens em chamada da IA"""
        today = str(date.today())

        if today not in self.daily_usage["daily"]:
            self.daily_usage["daily"][today] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                "ai_calls": 0,
            }

        input_cost = (input_tokens / 1000) * self.costs[model]["input"]
        output_cost = (output_tokens / 1000) * self.costs[model]["output"]
        total_cost = input_cost + output_cost

        self.daily_usage["daily"][today]["input_tokens"] += input_tokens
        self.daily_usage["daily"][today]["output_tokens"] += output_tokens
        self.daily_usage["daily"][today]["cost"] += total_cost
        self.daily_usage["daily"][today]["ai_calls"] += 1

        self.daily_usage["total_spent"] += total_cost
        self.daily_usage["ai_calls"] += 1

        self._save_usage()

        remaining = 10.0 - self.daily_usage["total_spent"]
        logger.info(
            f"💰 Tokens: {input_tokens}+{output_tokens} | "
            f"Custo: ${total_cost:.4f} | "
            f"Restante: ${remaining:.2f}"
        )

        return total_cost

    def track_cache_hit(self):
        """Registra hit no cache (economia de tokens)"""
        self.daily_usage["cache_hits"] += 1
        self._save_usage()
        logger.info("🎯 Cache hit - tokens economizados!")

    def get_summary(self) -> Dict[str, Any]:
        """Retorna resumo do uso"""
        remaining = 10.0 - self.daily_usage["total_spent"]
        today = str(date.today())
        today_usage = self.daily_usage["daily"].get(today, {})

        return {
            "budget_total": 10.0,
            "spent": self.daily_usage["total_spent"],
            "remaining": remaining,
            "percentage_used": (self.daily_usage["total_spent"] / 10.0) * 100,
            "today": today_usage,
            "cache_hits": self.daily_usage["cache_hits"],
            "ai_calls": self.daily_usage["ai_calls"],
            "cache_efficiency": (
                self.daily_usage["cache_hits"]
                / max(1, self.daily_usage["cache_hits"] + self.daily_usage["ai_calls"])
                * 100
            ),
        }

    def print_summary(self):
        """Imprime resumo formatado"""
        summary = self.get_summary()
        print("\n" + "=" * 50)
        print("💰 RESUMO DE GASTOS - OPENAI")
        print("=" * 50)
        print(f"Orçamento total: ${summary['budget_total']:.2f}")
        print(f"Gasto até agora: ${summary['spent']:.4f}")
        print(f"Restante: ${summary['remaining']:.2f}")
        print(f"Porcentagem usada: {summary['percentage_used']:.1f}%")
        print(f"\n📊 ESTATÍSTICAS:")
        print(f"Chamadas IA: {summary['ai_calls']}")
        print(f"Cache hits: {summary['cache_hits']}")
        print(f"Eficiência cache: {summary['cache_efficiency']:.1f}%")

        if summary["today"]:
            print(f"\n📅 HOJE:")
            print(f"Tokens entrada: {summary['today'].get('input_tokens', 0)}")
            print(f"Tokens saída: {summary['today'].get('output_tokens', 0)}")
            print(f"Custo hoje: ${summary['today'].get('cost', 0):.4f}")

        print("=" * 50 + "\n")


token_monitor = TokenMonitor()
