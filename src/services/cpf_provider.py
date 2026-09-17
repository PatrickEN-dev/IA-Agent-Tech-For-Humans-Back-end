"""Verificação de CPF junto a uma fonte externa.

Por que existe uma porta aqui em vez de uma chamada direta a alguma API: no Brasil não
há serviço público e gratuito que devolva nome e data de nascimento a partir de um CPF.
As fontes legítimas (Serpro Consulta CPF / Datavalid, e bureaus como BigDataCorp ou
Idwall) são pagas e exigem contrato com CNPJ; as "gratuitas" que aparecem em buscas são
bases vazadas, cujo uso viola a LGPD. Um projeto de portfólio não pode depender de
nenhuma das duas coisas.

A solução é a mesma que um time de produto adotaria antes de fechar o contrato: definir
a porta, implementar o adaptador real de acordo com o contrato publicado do fornecedor,
e rodar a aplicação com um adaptador local determinístico enquanto não há credencial.
Trocar um pelo outro é uma variável de ambiente, não um refactor.

    CPF_PROVIDER=mock    -> validação local de dígitos verificadores (padrão)
    CPF_PROVIDER=serpro  -> Serpro Consulta CPF, exige SERPRO_API_TOKEN

O `mock` nunca afirma que um CPF existe de verdade; ele responde "sintaticamente válido,
situação desconhecida", que é exatamente o que o app sabe sem consultar a Receita.
"""

import logging
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from src.config import get_settings
from src.utils.cpf import is_valid_cpf, mask_cpf, strip_cpf

logger = logging.getLogger(__name__)

CpfStatus = Literal["regular", "suspensa", "titular_falecido", "pendente", "desconhecida"]


@dataclass
class CpfVerification:
    """Resposta normalizada, igual para qualquer provedor."""

    cpf: str
    is_valid: bool
    status: CpfStatus
    nome: str | None = None
    data_nascimento: str | None = None
    provider: str = "mock"
    # Falso quando o provedor não conseguiu confirmar nada além da aritmética.
    verified_externally: bool = False
    message: str | None = None

    @property
    def can_register(self) -> bool:
        """Serve para abrir cadastro? Inválido ou irregular na Receita, não."""
        return self.is_valid and self.status in ("regular", "desconhecida")


class CpfVerificationProvider(Protocol):
    name: str

    async def verify(self, cpf: str) -> CpfVerification: ...

    async def aclose(self) -> None: ...


class MockCpfProvider:
    """Adaptador offline: só o que a aritmética garante.

    Determinístico e sem rede, então a suíte de testes e a demo funcionam em qualquer
    máquina, inclusive sem internet.
    """

    name = "mock"

    async def verify(self, cpf: str) -> CpfVerification:
        normalized = strip_cpf(cpf)
        valid = is_valid_cpf(normalized)
        return CpfVerification(
            cpf=normalized,
            is_valid=valid,
            status="desconhecida" if valid else "pendente",
            provider=self.name,
            verified_externally=False,
            message=(
                "CPF com dígitos verificadores válidos. A situação cadastral na Receita "
                "não é consultada neste ambiente de demonstração."
                if valid
                else "Os dígitos verificadores não conferem."
            ),
        )

    async def aclose(self) -> None:
        return None


class SerproCpfProvider:
    """Adaptador para a API Consulta CPF do Serpro.

    Escrito contra o contrato publicado do fornecedor, mas nunca exercitado contra o
    ambiente real: não há credencial neste projeto. Fica aqui como o caminho de
    produção e como o ponto exato onde a chave entraria — qualquer erro de rede ou de
    autorização degrada para o `MockCpfProvider` em vez de derrubar o cadastro.
    """

    name = "serpro"

    def __init__(self, fallback: CpfVerificationProvider | None = None) -> None:
        self._settings = get_settings()
        self._client: httpx.AsyncClient | None = None
        self._fallback = fallback or MockCpfProvider()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._settings.serpro_api_url,
                timeout=self._settings.cpf_provider_timeout_seconds,
                headers={"Authorization": f"Bearer {self._settings.serpro_api_token}"},
            )
        return self._client

    async def verify(self, cpf: str) -> CpfVerification:
        normalized = strip_cpf(cpf)

        # Aritmética primeiro: não gasta uma chamada paga com um CPF que já sabemos inválido.
        if not is_valid_cpf(normalized):
            return await self._fallback.verify(normalized)

        if not self._settings.serpro_api_token:
            logger.warning("CPF_PROVIDER=serpro sem SERPRO_API_TOKEN; usando fallback local")
            return await self._fallback.verify(normalized)

        try:
            response = await self._get_client().get(f"/cpf/{normalized}")
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            logger.warning(
                "Consulta Serpro falhou para %s (%s); usando fallback local",
                mask_cpf(normalized),
                exc.__class__.__name__,
            )
            return await self._fallback.verify(normalized)

        situacao = str(payload.get("situacao", {}).get("codigo", "")).strip()
        status: CpfStatus = {
            "0": "regular",
            "2": "suspensa",
            "3": "titular_falecido",
            "4": "pendente",
        }.get(situacao, "desconhecida")

        return CpfVerification(
            cpf=normalized,
            is_valid=True,
            status=status,
            nome=payload.get("nome"),
            data_nascimento=payload.get("nascimento"),
            provider=self.name,
            verified_externally=True,
            message=payload.get("situacao", {}).get("descricao"),
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        await self._fallback.aclose()


def build_cpf_provider() -> CpfVerificationProvider:
    settings = get_settings()
    if settings.cpf_provider == "serpro":
        return SerproCpfProvider()
    return MockCpfProvider()
