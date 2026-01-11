from fastapi import HTTPException, status


class AuthenticationError(HTTPException):
    def __init__(self, remaining_attempts: int) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Invalid CPF or birthdate",
                "remaining_attempts": remaining_attempts,
            },
        )


class MaxAttemptsExceededError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "message": "Maximum authentication attempts exceeded",
                "remaining_attempts": 0,
            },
        )


class ClientNotFoundError(HTTPException):
    def __init__(self, cpf: str) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client not found: {cpf[:3]}***",
        )


class InvalidTokenError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
