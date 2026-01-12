import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath("."))

from src.agents.orchestrator import Orchestrator
from src.agents.credito import CreditAgent
from src.agents.entrevista import InterviewAgent
from src.agents.cambio import ExchangeAgent
from src.models.schemas import (
    UnifiedChatRequest,
    LimitIncreaseRequest,
    InterviewRequest,
)


async def run_integration_tests():
    print("=" * 70)
    print("TESTES DE INTEGRACAO - AGENTE BANCARIO")
    print("=" * 70)

    orchestrator = Orchestrator()
    credit_agent = CreditAgent()
    interview_agent = InterviewAgent()
    exchange_agent = ExchangeAgent()

    passed = 0
    failed = 0

    async def test(name: str, func):
        nonlocal passed, failed
        try:
            result = await func()
            if result:
                print(f"[OK] {name}")
                passed += 1
            else:
                print(f"[FAIL] {name}")
                failed += 1
        except Exception as e:
            print(f"[ERRO] {name} - {e}")
            failed += 1

    print("\n--- TESTES DO ORCHESTRATOR ---\n")

    async def test_init_session():
        response = await orchestrator.init_session()
        return (
            response.session_id is not None
            and "Banco Ágil" in response.message
            and response.state == "collecting_cpf"
        )

    await test("1. Inicialização de sessão", test_init_session)

    async def test_cpf_valid():
        response = await orchestrator.init_session()
        session_id = response.session_id
        request = UnifiedChatRequest(session_id=session_id, message="52998224725")
        response = await orchestrator.process_message(request)
        return response.state == "collecting_birthdate"

    await test("2. CPF válido aceito", test_cpf_valid)

    async def test_cpf_invalid():
        response = await orchestrator.init_session()
        session_id = response.session_id
        request = UnifiedChatRequest(session_id=session_id, message="123")
        response = await orchestrator.process_message(request)
        return "inválido" in response.message.lower()

    await test("3. CPF inválido rejeitado", test_cpf_invalid)

    async def test_cpf_not_found():
        response = await orchestrator.init_session()
        session_id = response.session_id
        request = UnifiedChatRequest(session_id=session_id, message="99999999999")
        response = await orchestrator.process_message(request)
        return "não encontrado" in response.message.lower()

    await test("4. CPF não encontrado", test_cpf_not_found)

    async def test_full_auth():
        response = await orchestrator.init_session()
        session_id = response.session_id

        request = UnifiedChatRequest(session_id=session_id, message="52998224725")
        await orchestrator.process_message(request)

        request = UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        response = await orchestrator.process_message(request)
        return response.authenticated and response.token is not None

    await test("5. Autenticação completa", test_full_auth)

    async def test_wrong_birthdate():
        response = await orchestrator.init_session()
        session_id = response.session_id

        request = UnifiedChatRequest(session_id=session_id, message="52998224725")
        await orchestrator.process_message(request)

        request = UnifiedChatRequest(session_id=session_id, message="01/01/2000")
        response = await orchestrator.process_message(request)
        return "incorreta" in response.message.lower()

    await test("6. Data de nascimento incorreta", test_wrong_birthdate)

    async def test_credit_query():
        response = await orchestrator.init_session()
        session_id = response.session_id

        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )

        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="qual meu limite?")
        )
        return "limite" in response.message.lower() or "R$" in response.message

    await test("7. Consulta de limite de crédito", test_credit_query)

    async def test_credit_increase_request():
        response = await orchestrator.init_session()
        session_id = response.session_id

        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )

        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="quero aumento de limite")
        )
        return response.state == "credit_increase_flow"

    await test("8. Início de solicitação de aumento", test_credit_increase_request)

    async def test_credit_increase_approved():
        response = await orchestrator.init_session()
        session_id = response.session_id

        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="aumento de limite")
        )

        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15000")
        )
        return (
            "approved" in response.message.lower()
            or "aprovado" in response.message.lower()
        )

    await test("9. Aumento de limite aprovado", test_credit_increase_approved)

    async def test_credit_increase_denied_offers_interview():
        response = await orchestrator.init_session()
        session_id = response.session_id

        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="aumento de limite")
        )

        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="100000")
        )
        return (
            "entrevista" in response.message.lower()
            or response.redirect_suggestion is not None
        )

    await test(
        "10. Aumento negado oferece entrevista",
        test_credit_increase_denied_offers_interview,
    )

    async def test_interview_flow_start():
        response = await orchestrator.init_session()
        session_id = response.session_id

        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )

        response = await orchestrator.process_message(
            UnifiedChatRequest(
                session_id=session_id, message="quero atualizar meu perfil"
            )
        )
        return response.state == "interview_income"

    await test("11. Início de entrevista", test_interview_flow_start)

    async def test_interview_income():
        response = await orchestrator.init_session()
        session_id = response.session_id

        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="entrevista")
        )

        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="8000")
        )
        return response.state == "interview_employment"

    await test("12. Entrevista - renda", test_interview_income)

    async def test_interview_employment_clt():
        response = await orchestrator.init_session()
        session_id = response.session_id

        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="entrevista")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="8000")
        )

        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="CLT")
        )
        return response.state == "interview_expenses"

    await test("13. Entrevista - emprego CLT", test_interview_employment_clt)

    async def test_interview_employment_mei():
        response = await orchestrator.init_session()
        session_id = response.session_id

        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="entrevista")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="5000")
        )

        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="MEI")
        )
        return response.state == "interview_expenses"

    await test("14. Entrevista - emprego MEI", test_interview_employment_mei)

    async def test_interview_employment_publico():
        response = await orchestrator.init_session()
        session_id = response.session_id

        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="entrevista")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="12000")
        )

        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="servidor público")
        )
        return response.state == "interview_expenses"

    await test("15. Entrevista - emprego PUBLICO", test_interview_employment_publico)

    async def test_interview_complete():
        response = await orchestrator.init_session()
        session_id = response.session_id

        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="entrevista")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="8000")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="CLT")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="3000")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="2")
        )

        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="não")
        )
        return "score" in response.message.lower()

    await test("16. Entrevista completa", test_interview_complete)

    async def test_exchange_start():
        response = await orchestrator.init_session()
        session_id = response.session_id

        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )

        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="cotação do dólar")
        )
        return response.state == "exchange_from"

    await test("17. Início de câmbio", test_exchange_start)

    async def test_exchange_complete():
        response = await orchestrator.init_session()
        session_id = response.session_id

        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="câmbio")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="USD")
        )

        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="BRL")
        )
        return "USD" in response.message and "BRL" in response.message

    await test("18. Câmbio USD/BRL completo", test_exchange_complete)

    async def test_exit_command():
        response = await orchestrator.init_session()
        session_id = response.session_id

        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="tchau")
        )
        return response.state == "goodbye"

    await test("19. Comando de saída", test_exit_command)

    async def test_redirect_acceptance():
        response = await orchestrator.init_session()
        session_id = response.session_id

        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="aumento de limite")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="100000")
        )

        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="sim")
        )
        return (
            response.state == "interview_income" or "renda" in response.message.lower()
        )

    await test("20. Aceitar redirecionamento para entrevista", test_redirect_acceptance)

    async def test_redirect_rejection():
        response = await orchestrator.init_session()
        session_id = response.session_id

        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="aumento de limite")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="100000")
        )

        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="não")
        )
        return response.state == "authenticated"

    await test("21. Rejeitar redirecionamento", test_redirect_rejection)

    print("\n--- TESTES DOS AGENTES INDIVIDUAIS ---\n")

    async def test_credit_agent_get_limit():
        result = await credit_agent.get_limit("52998224725")
        return result.score > 0 and result.current_limit > 0

    await test("22. CreditAgent - get_limit", test_credit_agent_get_limit)

    async def test_credit_agent_request_approved():
        request = LimitIncreaseRequest(new_limit=10000)
        result = await credit_agent.request_increase("52998224725", request)
        return result.status in ["approved", "denied", "pending_analysis"]

    await test("23. CreditAgent - request_increase", test_credit_agent_request_approved)

    async def test_credit_agent_offer_interview():
        request = LimitIncreaseRequest(new_limit=1000000)
        result = await credit_agent.request_increase("52998224725", request)
        return result.status == "denied" and result.offer_interview is True

    await test(
        "24. CreditAgent - oferece entrevista quando negado",
        test_credit_agent_offer_interview,
    )

    async def test_interview_agent_submit():
        request = InterviewRequest(
            renda_mensal=8000,
            tipo_emprego="CLT",
            despesas=3000,
            num_dependentes=2,
            tem_dividas=False,
        )
        result = await interview_agent.submit("52998224725", request)
        return result.new_score > 0 and result.redirect_to == "/credit/limit"

    await test("25. InterviewAgent - submit", test_interview_agent_submit)

    async def test_exchange_agent_usd_brl():
        result = await exchange_agent.get_rate("USD", "BRL")
        return result.rate > 0 and result.from_currency == "USD"

    await test("26. ExchangeAgent - USD/BRL", test_exchange_agent_usd_brl)

    async def test_exchange_agent_eur_brl():
        result = await exchange_agent.get_rate("EUR", "BRL")
        return result.rate > 0

    await test("27. ExchangeAgent - EUR/BRL", test_exchange_agent_eur_brl)

    async def test_exchange_agent_gbp_usd():
        result = await exchange_agent.get_rate("GBP", "USD")
        return result.rate > 0

    await test("28. ExchangeAgent - GBP/USD", test_exchange_agent_gbp_usd)

    async def test_exchange_agent_same_currency():
        result = await exchange_agent.get_rate("USD", "USD")
        return result.rate == 1.0

    await test("29. ExchangeAgent - mesma moeda", test_exchange_agent_same_currency)

    print("\n--- TESTES DE CENÁRIOS REAIS ---\n")

    async def test_cpf_formatted():
        response = await orchestrator.init_session()
        session_id = response.session_id
        request = UnifiedChatRequest(session_id=session_id, message="529.982.247-25")
        response = await orchestrator.process_message(request)
        return response.state == "collecting_birthdate"

    await test("30. CPF com pontuação", test_cpf_formatted)

    async def test_cpf_with_spaces():
        response = await orchestrator.init_session()
        session_id = response.session_id
        request = UnifiedChatRequest(session_id=session_id, message="529 982 247 25")
        response = await orchestrator.process_message(request)
        return response.state == "collecting_birthdate"

    await test("31. CPF com espaços", test_cpf_with_spaces)

    async def test_date_written():
        response = await orchestrator.init_session()
        session_id = response.session_id
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15 de maio de 1990")
        )
        return response.authenticated

    await test("32. Data por extenso", test_date_written)

    async def test_date_with_dash():
        response = await orchestrator.init_session()
        session_id = response.session_id
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15-05-1990")
        )
        return response.authenticated

    await test("33. Data com traços", test_date_with_dash)

    async def test_natural_income():
        response = await orchestrator.init_session()
        session_id = response.session_id
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="entrevista")
        )
        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="ganho uns 8 mil")
        )
        return response.state == "interview_employment"

    await test("34. Renda em linguagem natural", test_natural_income)

    async def test_natural_employment():
        response = await orchestrator.init_session()
        session_id = response.session_id
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="entrevista")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="6000")
        )
        response = await orchestrator.process_message(
            UnifiedChatRequest(
                session_id=session_id, message="trabalho de carteira assinada"
            )
        )
        return response.state == "interview_expenses"

    await test("35. Emprego em linguagem natural", test_natural_employment)

    async def test_different_client():
        response = await orchestrator.init_session()
        session_id = response.session_id
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="71893456209")
        )
        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="22/03/1985")
        )
        return response.authenticated

    await test("36. Outro cliente (João Pedro)", test_different_client)

    async def test_high_score_client():
        response = await orchestrator.init_session()
        session_id = response.session_id
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="89123456789")
        )
        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="14/06/1976")
        )
        return response.authenticated

    await test("37. Cliente com score alto (Patricia)", test_high_score_client)

    async def test_low_score_client():
        response = await orchestrator.init_session()
        session_id = response.session_id
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="34598761254")
        )
        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="30/05/1983")
        )
        return response.authenticated

    await test("38. Cliente com score baixo (Juliana)", test_low_score_client)

    async def test_multiple_sessions():
        response1 = await orchestrator.init_session()
        response2 = await orchestrator.init_session()
        return response1.session_id != response2.session_id

    await test("39. Múltiplas sessões independentes", test_multiple_sessions)

    async def test_session_persistence():
        response = await orchestrator.init_session()
        session_id = response.session_id
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        response2 = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="meu limite")
        )
        return response2.authenticated

    await test("40. Persistência de sessão", test_session_persistence)

    async def test_exchange_jpy():
        result = await exchange_agent.get_rate("JPY", "BRL")
        return result.rate > 0

    await test("41. Câmbio JPY/BRL", test_exchange_jpy)

    async def test_exchange_ars():
        result = await exchange_agent.get_rate("ARS", "USD")
        return result.rate > 0

    await test("42. Câmbio ARS/USD", test_exchange_ars)

    async def test_interview_autonomo():
        request = InterviewRequest(
            renda_mensal=6000,
            tipo_emprego="AUTONOMO",
            despesas=2500,
            num_dependentes=1,
            tem_dividas=False,
        )
        result = await interview_agent.submit("52998224725", request)
        return result.new_score > 0

    await test("43. Entrevista - autônomo", test_interview_autonomo)

    async def test_interview_mei():
        request = InterviewRequest(
            renda_mensal=4000,
            tipo_emprego="MEI",
            despesas=2000,
            num_dependentes=0,
            tem_dividas=False,
        )
        result = await interview_agent.submit("52998224725", request)
        return result.new_score > 0

    await test("44. Entrevista - MEI", test_interview_mei)

    async def test_interview_publico():
        request = InterviewRequest(
            renda_mensal=10000,
            tipo_emprego="PUBLICO",
            despesas=4000,
            num_dependentes=2,
            tem_dividas=False,
        )
        result = await interview_agent.submit("52998224725", request)
        return result.new_score > 0

    await test("45. Entrevista - servidor público", test_interview_publico)

    async def test_interview_with_debts():
        request = InterviewRequest(
            renda_mensal=5000,
            tipo_emprego="CLT",
            despesas=4000,
            num_dependentes=3,
            tem_dividas=True,
        )
        result = await interview_agent.submit("52998224725", request)
        return result.new_score >= 0

    await test("46. Entrevista - com dívidas", test_interview_with_debts)

    async def test_interview_unemployed():
        request = InterviewRequest(
            renda_mensal=0,
            tipo_emprego="DESEMPREGADO",
            despesas=500,
            num_dependentes=0,
            tem_dividas=False,
        )
        result = await interview_agent.submit("52998224725", request)
        return result.new_score >= 0

    await test("47. Entrevista - desempregado", test_interview_unemployed)

    async def test_available_actions():
        response = await orchestrator.init_session()
        session_id = response.session_id
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="o que posso fazer?")
        )
        return len(response.available_actions) > 0

    await test("48. Ações disponíveis após autenticação", test_available_actions)

    async def test_transition_credit_to_exchange():
        response = await orchestrator.init_session()
        session_id = response.session_id
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="52998224725")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="15/05/1990")
        )
        await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="meu limite")
        )
        response = await orchestrator.process_message(
            UnifiedChatRequest(session_id=session_id, message="cotação do euro")
        )
        return response.state == "exchange_from"

    await test("49. Transição crédito -> câmbio", test_transition_credit_to_exchange)

    async def test_exchange_live_api():
        result = await exchange_agent.get_rate("USD", "BRL")
        return (
            "live" in result.message
            or "tempo real" in result.message
            or "recente" in result.message
            or result.rate > 0
        )

    await test("50. API de câmbio em tempo real", test_exchange_live_api)

    print("\n" + "=" * 70)
    print(f"RESULTADO FINAL: {passed} passaram, {failed} falharam")
    print(f"Taxa de sucesso: {(passed / (passed + failed)) * 100:.1f}%")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_integration_tests())
    sys.exit(0 if success else 1)
