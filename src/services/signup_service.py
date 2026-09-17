"""Auto-cadastro: o visitante abre a própria conta de demonstração.

É isto que resolve o problema real do produto — antes, testar o app exigia conhecer um
CPF que só estava num CSV dentro do repositório. Agora o visitante entra com um CPF que
ele mesmo escolhe (ou que o sistema gera para ele) e o fluxo inteiro passa a ser dele.

Nada aqui pede dado pessoal verdadeiro: o ambiente é de demonstração e a interface diz
isso. O CPF é validado pelos dígitos verificadores e passa pelo `CpfVerificationProvider`,
que em produção seria o Serpro.
"""

import logging
from dataclasses import dataclass
from datetime import date

from src.config import get_settings
from src.db.repositories import ClientRepository
from src.models.domain import Client
from src.services.address_service import AddressService
from src.services.cpf_provider import CpfVerificationProvider, MockCpfProvider
from src.services.score_service import ScoreService
from src.utils.cpf import generate_valid_cpf, is_valid_cpf, mask_cpf, strip_cpf

logger = logging.getLogger(__name__)

MAX_CPF_GENERATION_TRIES = 50


class SignupError(Exception):
    """Falha de regra de negócio no cadastro, com mensagem pronta para o cliente."""

    def __init__(self, message: str, *, code: str = "invalid") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class SignupResult:
    client: Client
    max_limit_for_score: float
    address_label: str | None
    cpf_provider: str
    cpf_verified_externally: bool


class SignupService:
    def __init__(
        self,
        client_repository: ClientRepository | None = None,
        score_service: ScoreService | None = None,
        address_service: AddressService | None = None,
        cpf_provider: CpfVerificationProvider | None = None,
    ) -> None:
        self._settings = get_settings()
        self._clients = client_repository or ClientRepository()
        self._score_service = score_service or ScoreService()
        self._addresses = address_service or AddressService()
        self._cpf_provider = cpf_provider or MockCpfProvider()

    async def suggest_cpf(self) -> str:
        """Gera um CPF válido e livre, para quem não quer digitar o próprio.

        A seed vem da contagem de clientes, então cada visitante recebe um número
        diferente sem precisar de aleatoriedade global.
        """
        base = await self._clients.count()
        for offset in range(MAX_CPF_GENERATION_TRIES):
            candidate = generate_valid_cpf(10_000 + base + offset)
            if not await self._clients.exists(candidate):
                return candidate
        raise SignupError(
            "Não consegui gerar um CPF livre agora. Tente novamente em instantes.",
            code="cpf_generation_failed",
        )

    @staticmethod
    def _validate_age(birthdate: date, min_age_years: int) -> None:
        today = date.today()
        if birthdate > today:
            raise SignupError(
                "A data de nascimento não pode estar no futuro.", code="birthdate_future"
            )

        age = today.year - birthdate.year - (
            (today.month, today.day) < (birthdate.month, birthdate.day)
        )
        if age < min_age_years:
            raise SignupError(
                f"É preciso ter pelo menos {min_age_years} anos para abrir conta.",
                code="underage",
            )
        if age > 120:
            raise SignupError(
                "Essa data de nascimento não parece correta. Confere o ano?",
                code="birthdate_implausible",
            )

    @staticmethod
    def validate_name(nome: str) -> str:
        cleaned = " ".join((nome or "").split())
        if len(cleaned) < 3:
            raise SignupError("Me diga seu nome completo, por favor.", code="name_too_short")
        if len(cleaned.split()) < 2:
            raise SignupError(
                "Preciso do nome e do sobrenome para abrir a conta.", code="name_incomplete"
            )
        if len(cleaned) > 120:
            raise SignupError("Esse nome é longo demais.", code="name_too_long")
        return cleaned

    async def register(
        self,
        *,
        nome: str,
        cpf: str | None,
        data_nascimento: date,
        email: str | None = None,
        cep: str | None = None,
    ) -> SignupResult:
        if not self._settings.signup_enabled:
            raise SignupError("O cadastro não está disponível.", code="disabled")

        nome = self.validate_name(nome)
        self._validate_age(data_nascimento, self._settings.signup_min_age_years)

        # CPF em branco significa "escolhe um pra mim": é o caminho de menor atrito
        # para quem só quer ver o produto funcionando.
        normalized_cpf = strip_cpf(cpf) if cpf else await self.suggest_cpf()

        if not is_valid_cpf(normalized_cpf):
            raise SignupError(
                "Esse número não é um CPF válido — os dígitos verificadores não batem.",
                code="cpf_invalid",
            )

        verification = await self._cpf_provider.verify(normalized_cpf)
        if not verification.can_register:
            raise SignupError(
                verification.message
                or "Não foi possível usar esse CPF para abrir conta agora.",
                code="cpf_rejected",
            )

        if await self._clients.exists(normalized_cpf):
            raise SignupError(
                "Já existe uma conta com esse CPF. Se for sua, é só entrar com o CPF e "
                "a data de nascimento.",
                code="cpf_taken",
            )

        address = await self._addresses.lookup(cep) if cep else None

        score = self._settings.signup_initial_score
        ceiling = await self._score_service.get_limit_for_score(score)
        # Conta nova não nasce no teto: um banco concede uma parte e deixa o resto para
        # o relacionamento. Aqui isso também é o que torna o produto demonstrável —
        # quem acabou de se cadastrar consegue pedir um aumento e vê-lo ser aprovado.
        initial_limit = round(ceiling * self._settings.signup_initial_limit_ratio, 2)

        client = await self._clients.create(
            Client(
                cpf=normalized_cpf,
                nome=nome,
                data_nascimento=data_nascimento.isoformat(),
                score=score,
                limite_atual=initial_limit,
                email=(email or "").strip() or None,
                cidade=address.cidade if address else None,
                uf=address.uf if address else None,
                cep=address.cep if address else (strip_cpf(cep) if cep else None),
                origem="signup",
                is_demo_persona=False,
            )
        )

        logger.info(
            "Auto-cadastro concluido: %s (score inicial %s, provider=%s)",
            mask_cpf(client.cpf),
            score,
            verification.provider,
        )

        return SignupResult(
            client=client,
            max_limit_for_score=ceiling,
            address_label=address.short() if address else None,
            cpf_provider=verification.provider,
            cpf_verified_externally=verification.verified_externally,
        )

    async def aclose(self) -> None:
        await self._addresses.aclose()
        await self._cpf_provider.aclose()
