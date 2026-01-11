import requests
import json


def test_ai_agent():
    url = "http://localhost:3001/api/chat"

    tests = [
        {
            "name": "Teste 1: Pergunta simples de boas-vindas",
            "payload": {"message": "olá", "conversation_history": []},
        },
        {
            "name": "Teste 2: Pergunta sobre matemática (fora de contexto)",
            "payload": {"message": "quanto é 25 x 34?", "conversation_history": []},
        },
        {
            "name": "Teste 3: Pergunta sobre história (fora de contexto)",
            "payload": {
                "message": "quem descobriu o Brasil?",
                "conversation_history": [],
            },
        },
        {
            "name": "Teste 4: Pergunta complexa sobre finanças (no contexto)",
            "payload": {
                "message": "explique como funciona o score de crédito",
                "conversation_history": [],
            },
        },
        {
            "name": "Teste 5: Pergunta sobre tecnologia (fora de contexto)",
            "payload": {
                "message": "o que é inteligência artificial?",
                "conversation_history": [],
            },
        },
    ]

    for test in tests:
        print(f"\n{test['name']}")
        print("=" * 50)

        try:
            response = requests.post(url, json=test["payload"], timeout=30)
            print(f"Status: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                print(f"Resposta: {result.get('message', 'Sem mensagem')}")
                print(f"Estado: {result.get('state', 'Sem estado')}")
                print(f"Session ID: {result.get('session_id', 'Sem ID')}")
            else:
                print(f"Erro: {response.text}")

        except requests.exceptions.Timeout:
            print("TIMEOUT - A IA demorou mais de 30s para responder")
        except requests.exceptions.ConnectionError:
            print("ERRO: Servidor não acessível")
        except Exception as e:
            print(f"ERRO: {e}")


if __name__ == "__main__":
    test_ai_agent()
