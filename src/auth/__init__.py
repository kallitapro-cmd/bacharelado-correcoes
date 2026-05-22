"""Autenticação (streamlit-authenticator). Implementado em Story 1.2."""

from src.auth.authenticator import (
    LGPD_BANNER_TEXT,
    LOCKOUT_DURATION_SECONDS,
    LOCKOUT_MESSAGE,
    MAX_LOGIN_ATTEMPTS,
    build_authenticator,
    is_lgpd_accepted,
    is_locked_out,
    load_config,
    register_failed_attempt,
    remaining_lockout_seconds,
    render_lgpd_banner,
    render_login,
    require_authentication,
    reset_attempts,
)

__all__ = [
    "LGPD_BANNER_TEXT",
    "LOCKOUT_DURATION_SECONDS",
    "LOCKOUT_MESSAGE",
    "MAX_LOGIN_ATTEMPTS",
    "build_authenticator",
    "is_lgpd_accepted",
    "is_locked_out",
    "load_config",
    "register_failed_attempt",
    "remaining_lockout_seconds",
    "render_lgpd_banner",
    "render_login",
    "require_authentication",
    "reset_attempts",
]
