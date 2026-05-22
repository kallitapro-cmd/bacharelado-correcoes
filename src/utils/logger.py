"""Safe logger com sanitização automática de dados sensíveis (Story 1.11).

Aplica filtros regex em todas as mensagens de log para censurar:
- RAs de alunos (11 dígitos) → ``[RA_REDACTED]``
- API keys Anthropic (``sk-ant-*``) → ``[API_KEY_REDACTED]``

Também customiza ``sys.excepthook`` para sanitizar stack traces de exceções
não tratadas antes de exibi-las em ``stderr``.

Conforme ADR-004 (LGPD e Retenção Zero), o sistema NUNCA pode persistir
dados pessoais ou credenciais em logs.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import TracebackType

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-ant-[a-zA-Z0-9_-]+"), "[API_KEY_REDACTED]"),
    (re.compile(r"\b\d{11}\b"), "[RA_REDACTED]"),
]


def sanitize(message: str) -> str:
    """Aplica todos os padrões de sanitização a uma mensagem."""
    for pattern, replacement in PATTERNS:
        message = pattern.sub(replacement, message)
    return message


class SanitizingFilter(logging.Filter):
    """Filtro de logging que sanitiza ``record.msg`` e ``record.args``."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = sanitize(str(record.msg))
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(sanitize(str(a)) for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: sanitize(str(v)) for k, v in record.args.items()}
        return True


def get_safe_logger(name: str) -> logging.Logger:
    """Retorna logger configurado com filtro de sanitização.

    Garante idempotência: se o logger já possui handlers, eles são reutilizados
    sem duplicação.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.addFilter(SanitizingFilter())
        logger.addHandler(handler)
    return logger


safe_logger = get_safe_logger("corretor_academico")

_original_excepthook = sys.excepthook


def _safe_excepthook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    """Intercepta exceções não tratadas e sanitiza antes de exibir em stderr."""
    import traceback

    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    sanitized = sanitize(tb_str)
    sys.stderr.write(sanitized)


sys.excepthook = _safe_excepthook
