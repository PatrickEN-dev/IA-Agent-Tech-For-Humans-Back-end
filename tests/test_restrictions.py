import asyncio
import sys
import os

# Adiciona o diretório do projeto ao path para importar os módulos
sys.path.insert(0, os.path.abspath("."))

from src.agents.optimized_chat import OptimizedChatAgent
from src.models.schemas import ChatRequest
from src.utils.token_monitor import token_monitor


async def test_banking_restrictions():
    """Testa se o agente está respeitando as restrições de contexto bancário"""

    print("🛡️ TESTANDO RESTRIÇÕES DE CONTEXTO BANCÁRIO")
    print("=" * 60)

    agent = OptimizedChatAgent()

    # Testes que DEVEM ser bloqueados (fora do contexto bancário)
    blocked_tests = [
        {"name": "❌ Matemática (deve ser bloqueado)", "message": "quanto é 25 x 34?"},
        {
            "name": "❌ História (deve ser bloqueado)",
            "message": "quem descobriu o Brasil?",
        },
        {
            "name": "❌ Tecnologia (deve ser bloqueado)",
            "message": "o que é inteligência artificial?",
        },
        {
            "name": "❌ Filosofia (deve ser bloqueado)",
            "message": "qual é o sentido da vida?",
        },
        {
            "name": "❌ Ciência (deve ser bloqueado)",
            "message": "como funciona a gravidade?",
        },
    ]

    # Testes que DEVEM ser permitidos (contexto bancário)
    allowed_tests = [
        {"name": "✅ Saudação (deve ser permitido)", "message": "olá"},
        {
            "name": "✅ Limite de crédito (deve ser permitido)",
            "message": "qual meu limite de crédito?",
        },
        {
            "name": "✅ Aumento de limite (deve ser permitido)",
            "message": "quero solicitar aumento de limite",
        },
        {
            "name": "✅ Câmbio (deve ser permitido)",
            "message": "qual a cotação do dólar?",
        },
        {
            "name": "✅ Score (deve ser permitido)",
            "message": "como funciona o score de crédito?",
        },
    ]

    session_id = None

    print("\n🚫 TESTANDO BLOQUEIOS (devem ser rejeitados):")
    print("-" * 50)

    for test in blocked_tests:
        print(f"\n{test['name']}")
        print(f"Pergunta: {test['message']}")

        try:
            request = ChatRequest(
                session_id=session_id, message=test["message"], conversation_history=[]
            )

            response = await agent.process_message(request)

            if not session_id:
                session_id = response.session_id

            # Verifica se foi bloqueado corretamente
            restricted_keywords = [
                "especializado apenas",
                "bancário",
                "cpf para validação",
            ]
            is_restricted = any(
                keyword in response.message.lower() for keyword in restricted_keywords
            )

            if is_restricted:
                print(f"✅ BLOQUEADO CORRETAMENTE")
            else:
                print(f"❌ FALHA: Não foi bloqueado!")

            print(f"Resposta: {response.message[:100]}...")

        except Exception as e:
            print(f"❌ ERRO: {e}")

    print(f"\n\n✅ TESTANDO PERMISSÕES (devem ser permitidos):")
    print("-" * 50)

    for test in allowed_tests:
        print(f"\n{test['name']}")
        print(f"Pergunta: {test['message']}")

        try:
            request = ChatRequest(
                session_id=session_id, message=test["message"], conversation_history=[]
            )

            response = await agent.process_message(request)

            # Verifica se foi permitido
            restricted_keywords = ["especializado apenas", "sou o assistente"]
            is_restricted = any(
                keyword in response.message.lower() for keyword in restricted_keywords
            )

            if not is_restricted or "banco ágil" in response.message.lower():
                print(f"✅ PERMITIDO CORRETAMENTE")
            else:
                print(f"❌ FALHA: Foi bloqueado incorretamente!")

            print(f"Resposta: {response.message[:100]}...")

        except Exception as e:
            print(f"❌ ERRO: {e}")

    print(f"\n{'='*60}")
    print("🏁 TESTE DE RESTRIÇÕES CONCLUÍDO!")

    # Mostra resumo de gastos
    token_monitor.print_summary()


if __name__ == "__main__":
    asyncio.run(test_banking_restrictions())
