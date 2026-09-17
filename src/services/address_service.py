"""Consulta de CEP via BrasilAPI.

Essa é uma integração externa de verdade: pública, gratuita, sem chave e sem dado
pessoal — o CEP devolve o logradouro, não quem mora nele. É o que dá ao cadastro a
sensação de produto (digitou o CEP, a cidade aparece sozinha) sem tocar em LGPD.

Falha de rede não pode travar o cadastro: o endereço é opcional, então qualquer erro
vira `None` e o fluxo segue.
"""

import logging
import re

import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)

CEP_LENGTH = 8


def strip_cep(cep: str) -> str:
    return re.sub(r"\D", "", cep or "")


def is_valid_cep(cep: str) -> bool:
    digits = strip_cep(cep)
    return len(digits) == CEP_LENGTH and digits != "0" * CEP_LENGTH


class Address:
    __slots__ = ("cep", "logradouro", "bairro", "cidade", "uf")

    def __init__(
        self,
        cep: str,
        logradouro: str | None,
        bairro: str | None,
        cidade: str,
        uf: str,
    ) -> None:
        self.cep = cep
        self.logradouro = logradouro
        self.bairro = bairro
        self.cidade = cidade
        self.uf = uf

    def short(self) -> str:
        parts = [p for p in (self.bairro, self.cidade) if p]
        return f"{', '.join(parts)} - {self.uf}" if parts else self.uf


class AddressService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._settings.address_api_timeout_seconds
            )
        return self._client

    async def lookup(self, cep: str) -> Address | None:
        digits = strip_cep(cep)
        if not is_valid_cep(digits):
            return None

        url = f"{self._settings.address_api_url.rstrip('/')}/{digits}"
        try:
            response = await self._get_client().get(url)
            if response.status_code == 404:
                logger.info("CEP nao encontrado: %s", digits)
                return None
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            # Endereço é opcional: indisponibilidade da BrasilAPI não impede o cadastro.
            logger.warning("Consulta de CEP falhou (%s)", exc.__class__.__name__)
            return None

        cidade = payload.get("city")
        uf = payload.get("state")
        if not cidade or not uf:
            return None

        return Address(
            cep=digits,
            logradouro=payload.get("street") or None,
            bairro=payload.get("neighborhood") or None,
            cidade=cidade,
            uf=uf,
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
