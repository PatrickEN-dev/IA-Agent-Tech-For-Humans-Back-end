import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath("."))

from src.agents.optimized_chat import OptimizedChatAgent
from src.models.schemas import ChatRequest
from src.utils.token_monitor import token_monitor


async def test_ai_agent_direct():
    """Testa o agente de IA diretamente sem servidor HTTP"""

    print("🤖 TESTANDO AGENTE DE IA DIRETAMENTE")
    print("=" * 60)

    agent = OptimizedChatAgent()

    tests = [
        {"name": "Teste 1: Pergunta simples de boas-vindas", "message": "olá"},
        {
            "name": "Teste 2: Pergunta sobre matemática (fora de contexto)",
            "message": "quanto é 25 x 34?",
        },
        {
            "name": "Teste 3: Pergunta sobre história (fora de contexto)",
            "message": "quem descobriu o Brasil?",
        },
        {
            "name": "Teste 4: Pergunta complexa sobre finanças (no contexto)",
            "message": "explique como funciona o score de crédito",
        },
        {
            "name": "Teste 5: Pergunta sobre tecnologia (fora de contexto)",
            "message": "o que é inteligência artificial?",
        },
        {
            "name": "Teste 6: Pergunta pessoal (fora de contexto)",
            "message": "qual é o sentido da vida?",
        },
    ]

    session_id = None

    for i, test in enumerate(tests, 1):
        print(f"\n{test['name']}")
        print("-" * 50)
        print(f"Pergunta: {test['message']}")

        try:
            request = ChatRequest(
                session_id=session_id, message=test["message"], conversation_history=[]
            )

            response = await agent.process_message(request)

            # Usa o session_id para continuar a conversa
            if not session_id:
                session_id = response.session_id

            print(f"✅ Resposta: {response.message}")
            print(f"📊 Estado: {response.state}")
            print(f"🔐 Autenticado: {response.authenticated}")

            # Adiciona uma pequena pausa entre testes
            await asyncio.sleep(1)

        except Exception as e:
            print(f"❌ ERRO: {e}")
            import traceback

            print(f"🔍 Detalhes: {traceback.format_exc()}")

    print(f"\n{'='*60}")
    print("🏁 TESTES CONCLUÍDOS!")

    token_monitor.print_summary()


def check_ai_configuration():
    """Verifica se a IA está configurada corretamente"""
    print("🔧 VERIFICANDO CONFIGURAÇÃO DA IA")
    print("=" * 50)

    from src.config import get_settings

    settings = get_settings()

    print(f"USE_LANGCHAIN: {settings.use_langchain}")
    print(f"LLM_PROVIDER: {settings.llm_provider}")

    has_openai = bool(
        settings.openai_api_key and settings.openai_api_key != "your-openai-api-key"
    )
    has_anthropic = bool(
        settings.anthropic_api_key
        and settings.anthropic_api_key != "your-anthropic-api-key"
    )

    print(f"OPENAI_API_KEY configurado: {has_openai}")
    print(f"ANTHROPIC_API_KEY configurado: {has_anthropic}")
    print(f"LLM disponível: {settings.has_llm_api_key()}")

    if not settings.use_langchain:
        print("⚠️  AVISO: USE_LANGCHAIN está False - usando fallback")
    elif not settings.has_llm_api_key():
        print("⚠️  AVISO: Nenhuma chave de API válida encontrada - usando fallback")
    else:
        print("✅ IA CONFIGURADA CORRETAMENTE!")

    print()


if __name__ == "__main__":
    check_ai_configuration()
    asyncio.run(test_ai_agent_direct())
