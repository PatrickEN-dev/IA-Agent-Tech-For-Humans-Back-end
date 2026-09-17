"""Auto-cadastro: o caminho que dispensa conhecer um CPF da base."""

from datetime import date

import pytest
from httpx import AsyncClient

from src.api.routes import client_repository, signup_service
from src.config import get_settings
from src.services.address_service import Address
from src.services.cpf_provider import CpfVerification, MockCpfProvider
from src.services.signup_service import SignupError, SignupService
from src.utils.cpf import is_valid_cpf


async def say(client: AsyncClient, session_id: str | None, message: str) -> dict:
    response = await client.post(
        "/unified/chat", json={"session_id": session_id, "message": message}
    )
    assert response.status_code == 200
    return response.json()


# ------------------------------------------------------------------ endpoint


@pytest.mark.asyncio
async def test_signup_gera_cpf_quando_nao_informado(client: AsyncClient) -> None:
    response = await client.post(
        "/signup", json={"nome": "Ana Teste", "data_nascimento": "1992-04-10"}
    )
    assert response.status_code == 201

    data = response.json()
    assert is_valid_cpf(data["cpf"])
    assert data["score"] == get_settings().signup_initial_score
    assert data["current_limit"] > 0
    assert data["cpf_provider"] == "mock"
    # O mock nunca finge ter consultado a Receita.
    assert data["cpf_verified_externally"] is False


@pytest.mark.asyncio
async def test_signup_aceita_cpf_informado_e_permite_login(client: AsyncClient) -> None:
    response = await client.post(
        "/signup",
        json={
            "nome": "Bruno Teste",
            "cpf": "529.982.247-25",
            "data_nascimento": "1988-07-21",
        },
    )
    assert response.status_code == 201
    assert response.json()["cpf"] == "52998224725"

    # A conta criada funciona no fluxo normal de autenticacao.
    auth = await client.post(
        "/triage/authenticate",
        json={"cpf": "52998224725", "birthdate": "1988-07-21"},
    )
    assert auth.status_code == 200
    assert auth.json()["authenticated"] is True


@pytest.mark.asyncio
async def test_signup_rejeita_cpf_invalido(client: AsyncClient) -> None:
    response = await client.post(
        "/signup",
        json={
            "nome": "Carla Teste",
            "cpf": "12345678901",
            "data_nascimento": "1990-01-01",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "cpf_invalid"


@pytest.mark.asyncio
async def test_signup_rejeita_cpf_ja_cadastrado(client: AsyncClient) -> None:
    response = await client.post(
        "/signup",
        json={
            "nome": "Maria Duplicada",
            "cpf": "12345678909",
            "data_nascimento": "1990-05-15",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cpf_taken"


@pytest.mark.asyncio
async def test_signup_rejeita_menor_de_idade(client: AsyncClient) -> None:
    hoje = date.today()
    menor = hoje.replace(year=hoje.year - 15)
    response = await client.post(
        "/signup", json={"nome": "Jovem Teste", "data_nascimento": menor.isoformat()}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "underage"


@pytest.mark.asyncio
async def test_signup_exige_sobrenome(client: AsyncClient) -> None:
    response = await client.post(
        "/signup", json={"nome": "Fulano", "data_nascimento": "1990-01-01"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "name_incomplete"


@pytest.mark.asyncio
async def test_signup_404_quando_desabilitado(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "signup_enabled", False)
    response = await client.post(
        "/signup", json={"nome": "Alguem Teste", "data_nascimento": "1990-01-01"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cpf_sugerido_e_valido_e_livre(client: AsyncClient) -> None:
    response = await client.get("/signup/suggested-cpf")
    assert response.status_code == 200

    data = response.json()
    assert is_valid_cpf(data["cpf"])
    assert data["cpf_formatado"].count(".") == 2
    assert await client_repository.get_by_cpf(data["cpf"]) is None


# ------------------------------------------------------------------ serviço


@pytest.mark.asyncio
async def test_endereco_preenche_cidade_e_uf(monkeypatch: pytest.MonkeyPatch) -> None:
    """O CEP vem de uma API externa; aqui ela é dublada para o teste não sair para a rede."""

    class FakeAddresses:
        async def lookup(self, cep: str) -> Address:
            return Address(
                cep="01310100",
                logradouro="Avenida Paulista",
                bairro="Bela Vista",
                cidade="São Paulo",
                uf="SP",
            )

        async def aclose(self) -> None:
            return None

    service = SignupService(client_repository, address_service=FakeAddresses())
    result = await service.register(
        nome="Denise Teste",
        cpf=None,
        data_nascimento=date(1991, 3, 3),
        cep="01310-100",
    )

    assert result.client.cidade == "São Paulo"
    assert result.client.uf == "SP"
    assert result.address_label == "Bela Vista, São Paulo - SP"


@pytest.mark.asyncio
async def test_cadastro_segue_sem_endereco_quando_cep_falha() -> None:
    """Indisponibilidade da API de CEP não pode derrubar o cadastro."""

    class BrokenAddresses:
        async def lookup(self, cep: str) -> None:
            return None

        async def aclose(self) -> None:
            return None

    service = SignupService(client_repository, address_service=BrokenAddresses())
    result = await service.register(
        nome="Eduardo Teste",
        cpf=None,
        data_nascimento=date(1991, 3, 3),
        cep="99999999",
    )

    assert result.client.cidade is None
    assert result.address_label is None


@pytest.mark.asyncio
async def test_provedor_que_recusa_o_cpf_impede_o_cadastro() -> None:
    """Situação cadastral irregular na Receita bloqueia a abertura de conta."""

    class RejectingProvider:
        name = "fake"

        async def verify(self, cpf: str) -> CpfVerification:
            return CpfVerification(
                cpf=cpf,
                is_valid=True,
                status="suspensa",
                provider=self.name,
                message="CPF com situação suspensa.",
            )

        async def aclose(self) -> None:
            return None

    service = SignupService(client_repository, cpf_provider=RejectingProvider())

    with pytest.raises(SignupError) as exc:
        await service.register(
            nome="Fabio Teste", cpf=None, data_nascimento=date(1990, 1, 1)
        )
    assert exc.value.code == "cpf_rejected"


@pytest.mark.asyncio
async def test_mock_provider_nao_afirma_situacao_cadastral() -> None:
    verification = await MockCpfProvider().verify("52998224725")
    assert verification.is_valid is True
    assert verification.status == "desconhecida"
    assert verification.verified_externally is False
    assert verification.can_register is True


@pytest.mark.asyncio
async def test_cpfs_sugeridos_nao_se_repetem() -> None:
    primeiro = await signup_service.suggest_cpf()
    await signup_service.register(
        nome="Gabriela Teste", cpf=primeiro, data_nascimento=date(1990, 2, 2)
    )
    segundo = await signup_service.suggest_cpf()
    assert segundo != primeiro


# ------------------------------------------------------------------ chat


@pytest.mark.asyncio
async def test_fluxo_de_cadastro_pelo_chat(client: AsyncClient) -> None:
    session_id = (await client.post("/unified/init")).json()["session_id"]

    data = await say(client, session_id, "não tenho conta")
    assert data["state"] == "signup_name"

    data = await say(client, session_id, "Helena Prado")
    assert data["state"] == "signup_birthdate"
    assert "Helena" in data["message"]

    data = await say(client, session_id, "20/08/1993")
    assert data["state"] == "signup_cpf"

    data = await say(client, session_id, "gera um pra mim")
    assert data["state"] == "signup_cep"

    data = await say(client, session_id, "pular")
    assert data["state"] == "authenticated"
    assert data["authenticated"] is True
    assert data["token"]
    assert data["user_name"] == "Helena"

    # A conta recem-criada opera normalmente.
    data = await say(client, session_id, "meu limite")
    assert "R$" in data["message"]


@pytest.mark.asyncio
async def test_cadastro_pelo_chat_recusa_cpf_invalido(client: AsyncClient) -> None:
    session_id = (await client.post("/unified/init")).json()["session_id"]
    await say(client, session_id, "quero criar conta")
    await say(client, session_id, "Igor Nunes")
    await say(client, session_id, "01/01/1990")

    data = await say(client, session_id, "12345678901")
    assert data["state"] == "signup_cpf"
    assert "verificadores" in data["message"].lower()


@pytest.mark.asyncio
async def test_cadastro_pelo_chat_pode_ser_cancelado(client: AsyncClient) -> None:
    session_id = (await client.post("/unified/init")).json()["session_id"]
    await say(client, session_id, "criar conta")

    data = await say(client, session_id, "cancelar")
    assert data["state"] == "collecting_cpf"
    assert data["authenticated"] is False


@pytest.mark.asyncio
async def test_cpf_desconhecido_oferece_caminho_de_saida(client: AsyncClient) -> None:
    """O visitante que digita o próprio CPF não pode ficar sem alternativa."""
    session_id = (await client.post("/unified/init")).json()["session_id"]
    data = await say(client, session_id, "52998224725")

    assert data["state"] == "collecting_cpf"
    mensagem = data["message"].lower()
    assert "demonstra" in mensagem
    assert "criar conta" in mensagem


@pytest.mark.asyncio
async def test_conta_nova_nasce_com_espaco_para_aumento(client: AsyncClient) -> None:
    """Quem acabou de se cadastrar precisa conseguir pedir um aumento e ver aprovado.

    Nascer no teto deixava o caminho mais importante do produto inalcançável para
    quem acabou de entrar.
    """
    criada = await client.post(
        "/signup", json={"nome": "Helena Nova", "data_nascimento": "1990-06-06"}
    )
    assert criada.status_code == 201

    data = criada.json()
    assert data["current_limit"] < data["max_limit_for_score"]

    auth = await client.post(
        "/triage/authenticate",
        json={"cpf": data["cpf"], "birthdate": "1990-06-06"},
    )
    token = auth.json()["token"]

    aumento = await client.post(
        "/credit/request_increase",
        headers={"Authorization": f"Bearer {token}"},
        json={"new_limit": data["max_limit_for_score"]},
    )
    assert aumento.status_code == 200
    assert aumento.json()["status"] == "approved"
