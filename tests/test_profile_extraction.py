"""Entrevista conversacional: várias respostas em uma frase, e confirmação antes de gravar."""

import pytest
from httpx import AsyncClient

from src.api.routes import client_repository
from src.utils.profile_extractor import extract_profile
from tests.conftest import TEST_CPF


async def say(client: AsyncClient, session_id: str | None, message: str) -> dict:
    response = await client.post(
        "/unified/chat", json={"session_id": session_id, "message": message}
    )
    assert response.status_code == 200
    return response.json()


async def authenticate(client: AsyncClient) -> str:
    session_id = (await client.post("/unified/init")).json()["session_id"]
    await say(client, session_id, TEST_CPF)
    data = await say(client, session_id, "15/05/1990")
    assert data["authenticated"] is True
    return session_id


class TestExtrator:
    def test_frase_completa_preenche_os_cinco_campos(self) -> None:
        draft = extract_profile(
            "Ganho 8 mil, sou CLT, gasto 3 mil, dois filhos, sem dívidas"
        )
        assert draft.renda_mensal == 8000.0
        assert draft.tipo_emprego == "CLT"
        assert draft.despesas == 3000.0
        assert draft.num_dependentes == 2
        assert draft.tem_dividas is False
        assert draft.is_complete

    def test_valores_sao_ancorados_no_rotulo(self) -> None:
        """"ganho 8 mil, gasto 3 mil": cada número vai para o campo do seu rótulo."""
        draft = extract_profile("ganho 8 mil e gasto 3 mil")
        assert draft.renda_mensal == 8000.0
        assert draft.despesas == 3000.0

    def test_dependentes_usam_o_numero_adjacente(self) -> None:
        """Em "gasto 3 mil, dois filhos" o 3 é despesa, não a contagem de filhos."""
        draft = extract_profile("gasto 3 mil, dois filhos")
        assert draft.num_dependentes == 2
        assert draft.despesas == 3000.0

    def test_valor_sem_rotulo_nao_e_adivinhado(self) -> None:
        """Errar a renda de alguém em silêncio é pior do que fazer mais uma pergunta."""
        draft = extract_profile("8000")
        assert draft.renda_mensal is None
        assert draft.missing() == list(draft.FIELDS)

    def test_negacao_de_divida_vem_antes_da_palavra_divida(self) -> None:
        assert extract_profile("não tenho dívidas").tem_dividas is False
        assert extract_profile("sem dívidas").tem_dividas is False
        assert extract_profile("nome limpo").tem_dividas is False
        assert extract_profile("tenho dívidas").tem_dividas is True
        assert extract_profile("estou negativado").tem_dividas is True

    def test_ausencia_de_dependentes(self) -> None:
        assert extract_profile("sem filhos").num_dependentes == 0
        assert extract_profile("não tenho dependentes").num_dependentes == 0
        assert extract_profile("moro sozinho").num_dependentes == 0

    def test_renda_igual_a_despesa_e_tratada_como_leitura_duplicada(self) -> None:
        """Um número só na frase não pode virar renda e despesa ao mesmo tempo."""
        draft = extract_profile("minha renda e meu gasto é 5 mil")
        assert draft.renda_mensal == 5000.0
        assert draft.despesas is None

    def test_valor_implausivel_e_descartado(self) -> None:
        draft = extract_profile("ganho 50 milhões por mês")
        assert draft.renda_mensal is None
        assert "renda_mensal" in draft.descartados

    def test_texto_vazio(self) -> None:
        assert extract_profile("").missing() == list(extract_profile("").FIELDS)


class TestEntrevistaConversacional:
    @pytest.mark.asyncio
    async def test_uma_frase_pula_direto_para_a_confirmacao(
        self, client: AsyncClient
    ) -> None:
        session_id = await authenticate(client)

        data = await say(
            client,
            session_id,
            "quero atualizar meu perfil: ganho 8 mil, sou CLT, gasto 3 mil, "
            "dois filhos e não tenho dívidas",
        )

        # Nenhuma das cinco perguntas precisou ser feita.
        assert data["state"] == "interview_confirm"
        mensagem = data["message"]
        assert "R$ 8.000,00" in mensagem
        assert "R$ 3.000,00" in mensagem
        assert "CLT" in mensagem
        assert "Dependentes: 2" in mensagem

    @pytest.mark.asyncio
    async def test_frase_parcial_pergunta_so_o_que_falta(
        self, client: AsyncClient
    ) -> None:
        session_id = await authenticate(client)

        data = await say(client, session_id, "atualizar perfil, ganho 10 mil e sou CLT")
        # Renda e vínculo já vieram; a próxima pergunta é a de despesas.
        assert data["state"] == "interview_expenses"
        assert "R$ 10.000,00" in data["message"]

        data = await say(client, session_id, "gasto 4 mil, sem filhos e sem dívidas")
        assert data["state"] == "interview_confirm"

    @pytest.mark.asyncio
    async def test_resposta_traz_mais_do_que_foi_perguntado(
        self, client: AsyncClient
    ) -> None:
        """A resposta à pergunta de renda costuma trazer o resto junto."""
        session_id = await authenticate(client)
        await say(client, session_id, "atualizar perfil")

        data = await say(client, session_id, "ganho 9 mil, sou MEI e tenho 1 filho")
        # Pula emprego e dependentes: só falta despesas.
        assert data["state"] == "interview_expenses"

    @pytest.mark.asyncio
    async def test_recusar_a_confirmacao_refaz_a_coleta(
        self, client: AsyncClient
    ) -> None:
        session_id = await authenticate(client)
        await say(
            client,
            session_id,
            "atualizar perfil: ganho 8 mil, CLT, gasto 3 mil, sem filhos, sem dívidas",
        )

        antes = await client_repository.get_by_cpf(TEST_CPF)
        data = await say(client, session_id, "não")

        assert data["state"] == "interview_income"
        # Nada foi gravado: recusar a confirmacao nao pode alterar o score.
        depois = await client_repository.get_by_cpf(TEST_CPF)
        assert depois.score == antes.score

    @pytest.mark.asyncio
    async def test_confirmacao_ambigua_repete_o_resumo(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        await say(
            client,
            session_id,
            "atualizar perfil: ganho 8 mil, CLT, gasto 3 mil, sem filhos, sem dívidas",
        )

        data = await say(client, session_id, "sei lá")
        assert data["state"] == "interview_confirm"
        assert "Renda mensal" in data["message"]

    @pytest.mark.asyncio
    async def test_aceitar_grava_e_deixa_rastro(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        await say(
            client,
            session_id,
            "atualizar perfil: ganho 15 mil, CLT, gasto 2 mil, sem filhos, sem dívidas",
        )

        data = await say(client, session_id, "sim")
        assert data["state"] == "authenticated"
        assert "score" in data["message"].lower()

        eventos = await client_repository.list_score_events(TEST_CPF)
        assert eventos and eventos[0].origem == "entrevista"

    @pytest.mark.asyncio
    async def test_cancelar_funciona_no_meio_da_coleta(self, client: AsyncClient) -> None:
        session_id = await authenticate(client)
        await say(client, session_id, "atualizar perfil, ganho 10 mil")

        data = await say(client, session_id, "cancelar")
        assert data["state"] == "authenticated"
