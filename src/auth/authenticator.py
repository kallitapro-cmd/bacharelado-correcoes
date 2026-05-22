"""Autenticação do Corretor Acadêmico (Story 1.2).

Wrapper sobre ``streamlit-authenticator`` que adiciona:

- Banner de consentimento LGPD obrigatório antes do login (ADR-004).
- Campo "Seu nome (identificação)" exposto ao PA para audit trail
  (registrado em ``st.session_state['identificacao_pa']``).
- Lockout local de 15 minutos após 5 tentativas erradas (``st.session_state``).
- Cookie com expiração de 1 dia.

A configuração (usuários, hashes bcrypt, chave de cookie) é carregada a
partir de ``config.yaml`` na raiz do projeto. Esse arquivo NÃO é
versionado — use ``config.yaml.example`` como referência.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import streamlit as st
import streamlit_authenticator as stauth
import yaml

if TYPE_CHECKING:
    from collections.abc import Mapping

# --- Constantes públicas (parâmetros de segurança da Story 1.2) -------------

#: Número máximo de tentativas de login antes do lockout.
MAX_LOGIN_ATTEMPTS: Final[int] = 5

#: Duração do lockout em segundos (15 minutos).
LOCKOUT_DURATION_SECONDS: Final[int] = 15 * 60

#: Mensagem exibida durante o lockout.
LOCKOUT_MESSAGE: Final[str] = (
    "Muitas tentativas incorretas. Por segurança, o acesso está pausado. "
    "Tente novamente em 15 minutos."
)

#: Mensagem exibida quando a sessão anterior expirou (H2).
SESSION_EXPIRED_MESSAGE: Final[str] = "Sua sessão anterior expirou. Por favor, entre novamente."

#: Texto do banner de consentimento LGPD (ADR-004 — wording inalterado).
LGPD_BANNER_TEXT: Final[str] = (
    "Este sistema processa notas e feedbacks de atividades acadêmicas. "
    "Os dados são utilizados exclusivamente para correção automatizada e "
    "não são armazenados em servidores externos. Sua sessão não persiste "
    "dados pessoais após o encerramento. Ao continuar, você confirma que "
    "tem autorização para acessar os dados das turmas."
)

#: Caminho default da configuração (resolvido a partir da raiz do projeto).
DEFAULT_CONFIG_PATH: Final[Path] = Path(__file__).resolve().parents[2] / "config.yaml"


def _load_config_from_secrets() -> dict[str, Any]:
    """Carrega configuração a partir de ``st.secrets`` (Streamlit Cloud)."""
    auth_secrets = st.secrets["auth"]
    return {
        "credentials": dict(auth_secrets["credentials"]),
        "cookie": dict(auth_secrets["cookie"]),
    }


# --- Chaves de session_state (centralizadas para facilitar manutenção) ------

_KEY_ATTEMPTS: Final[str] = "login_attempts"
_KEY_LOCKOUT_UNTIL: Final[str] = "lockout_until"
_KEY_LGPD_ACCEPTED: Final[str] = "lgpd_accepted"
_KEY_IDENTIFICACAO_PA: Final[str] = "identificacao_pa"
_KEY_HAD_SESSION: Final[str] = "had_session"


# --- Carregamento de configuração -------------------------------------------


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Carrega ``config.yaml`` em um dicionário.

    Args:
        config_path: caminho alternativo; default é ``DEFAULT_CONFIG_PATH``.

    Returns:
        Dicionário com as seções ``credentials``, ``cookie`` e
        ``preauthorized``.

    Raises:
        FileNotFoundError: se o arquivo não existir.
        ValueError: se o conteúdo não for um mapeamento YAML válido.
    """

    path = config_path or DEFAULT_CONFIG_PATH
    if not path.is_file():
        raise FileNotFoundError(
            f"Arquivo de configuração não encontrado: {path}. "
            "Copie 'config.yaml.example' para 'config.yaml' e ajuste."
        )

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise ValueError("config.yaml inválido: o nível raiz precisa ser um mapeamento YAML.")

    missing = [k for k in ("credentials", "cookie") if k not in raw]
    if missing:
        raise ValueError(
            f"config.yaml inválido: chave(s) obrigatória(s) ausente(s): "
            f"{', '.join(missing)}. Verifique config.yaml.example."
        )

    return raw


def build_authenticator(
    config: Mapping[str, Any] | None = None,
    config_path: Path | None = None,
) -> stauth.Authenticate:
    """Constrói um ``streamlit_authenticator.Authenticate``.

    O cookie é configurado com ``expiry_days=1`` (AC #5).

    Args:
        config: configuração já carregada (útil em testes); se ``None``
            carrega a partir de ``config_path``/``DEFAULT_CONFIG_PATH``.
        config_path: caminho alternativo do ``config.yaml``.

    Returns:
        Instância pronta para chamar ``.login()`` em um app Streamlit.
    """

    if config is not None:
        cfg = dict(config)
    elif "auth" in st.secrets:
        cfg = _load_config_from_secrets()
    else:
        cfg = load_config(config_path)
    cookie_cfg = cfg.get("cookie", {})

    return stauth.Authenticate(
        credentials=cfg.get("credentials", {}),
        cookie_name=cookie_cfg.get("name", "corretor_academico_cookie"),
        cookie_key=cookie_cfg.get("key", ""),
        cookie_expiry_days=1,
    )


# --- LGPD ------------------------------------------------------------------


def is_lgpd_accepted() -> bool:
    """Indica se o banner LGPD já foi aceito nesta sessão."""

    return bool(st.session_state.get(_KEY_LGPD_ACCEPTED, False))


def render_lgpd_banner() -> bool:
    """Renderiza o banner de consentimento LGPD (AC #4).

    Returns:
        ``True`` se o usuário já aceitou; ``False`` caso contrário (o
        chamador deve interromper o fluxo de login enquanto o consentimento
        não for dado).
    """

    if is_lgpd_accepted():
        return True

    st.warning(LGPD_BANNER_TEXT)
    if st.button("Confirmar e continuar", key="lgpd_confirm"):
        st.session_state[_KEY_LGPD_ACCEPTED] = True
        # Re-executa o script para que o formulário apareça imediatamente.
        st.rerun()
    return False


# --- Lockout ---------------------------------------------------------------


def _now() -> float:
    """Indireção para facilitar o mock em testes."""

    return time.time()


def is_locked_out() -> bool:
    """Indica se o usuário está em lockout neste instante."""

    lockout_until = st.session_state.get(_KEY_LOCKOUT_UNTIL)
    if lockout_until is None:
        return False
    if _now() >= float(lockout_until):
        # Expirou — limpa para permitir nova tentativa.
        st.session_state.pop(_KEY_LOCKOUT_UNTIL, None)
        st.session_state[_KEY_ATTEMPTS] = 0
        return False
    return True


def remaining_lockout_seconds() -> int:
    """Segundos restantes de lockout (0 se não houver lockout)."""

    lockout_until = st.session_state.get(_KEY_LOCKOUT_UNTIL)
    if lockout_until is None:
        return 0
    remaining = float(lockout_until) - _now()
    return max(0, int(remaining))


def register_failed_attempt() -> bool:
    """Registra uma tentativa errada e ativa lockout se atingir o limite.

    Returns:
        ``True`` se o lockout foi acionado pela tentativa registrada.
    """

    attempts = int(st.session_state.get(_KEY_ATTEMPTS, 0)) + 1
    st.session_state[_KEY_ATTEMPTS] = attempts

    if attempts >= MAX_LOGIN_ATTEMPTS:
        st.session_state[_KEY_LOCKOUT_UNTIL] = _now() + LOCKOUT_DURATION_SECONDS
        return True
    return False


def reset_attempts() -> None:
    """Reseta o contador de tentativas e o lockout (chamar após sucesso)."""

    st.session_state[_KEY_ATTEMPTS] = 0
    st.session_state.pop(_KEY_LOCKOUT_UNTIL, None)


# --- Fluxo principal de login ----------------------------------------------


def render_login(
    authenticator: stauth.Authenticate,
) -> tuple[str | None, bool | None, str | None]:
    """Renderiza o fluxo de login completo (banner + identificação + form).

    Etapas:

    1. Mostra o banner LGPD; bloqueia até o usuário aceitar.
    2. Se o usuário estiver em lockout, exibe mensagem e interrompe.
    3. Coleta o campo "Seu nome (identificação)" para audit trail.
    4. Delega para ``Authenticate.login()`` o formulário de credenciais.
    5. Atualiza contador de tentativas e popula
       ``st.session_state['identificacao_pa']`` em caso de sucesso.

    Returns:
        Tripla ``(name, authentication_status, username)`` no mesmo formato
        de ``streamlit_authenticator.Authenticate.login``. Valores podem
        ser ``None`` se o usuário ainda não submeteu o formulário ou
        se o fluxo foi interrompido (banner pendente / lockout).
    """

    if not render_lgpd_banner():
        return None, None, None

    # H2 — Sessão expirada: exibe aviso quando havia sessão anterior mas não há autenticação ativa.
    if st.session_state.get(_KEY_HAD_SESSION) and not st.session_state.get("authentication_status"):
        st.info(SESSION_EXPIRED_MESSAGE)

    if is_locked_out():
        # H3 — Lockout com contagem regressiva.
        st.error(LOCKOUT_MESSAGE)
        remaining = remaining_lockout_seconds()
        mins, secs = divmod(remaining, 60)
        st.info(f"Você pode tentar novamente em {mins} min {secs} seg.")
        return None, False, None

    # H1 — Subtítulo orientando o PA antes do campo de identificação.
    st.caption("Antes de entrar, informe seu nome para registro")
    identificacao = st.text_input(
        "Seu nome (identificação)",
        key="input_identificacao_pa",
        help="Seu nome aparecerá nos relatórios de correção.",  # M1
    )

    name, authentication_status, username = authenticator.login(
        location="main",
        fields={
            "Form name": "Login",
            "Username": "Usuário",
            "Password": "Senha",
            "Login": "Entrar",
        },
    )

    if authentication_status is True:
        reset_attempts()
        st.session_state[_KEY_IDENTIFICACAO_PA] = identificacao.strip() if identificacao else ""
        st.session_state[_KEY_HAD_SESSION] = True
    elif authentication_status is False:
        triggered = register_failed_attempt()
        if triggered:
            st.error(LOCKOUT_MESSAGE)
        else:
            tentativas_feitas = int(st.session_state.get(_KEY_ATTEMPTS, 0))
            restantes = MAX_LOGIN_ATTEMPTS - tentativas_feitas
            # M2 — Aviso de bloqueio só a partir da 3ª tentativa.
            if tentativas_feitas >= 3:
                st.error(
                    "Usuário ou senha incorretos. "
                    f"Mais {restantes} tentativa(s) antes de uma pausa de 15 minutos."
                )
            else:
                st.error("Usuário ou senha incorretos. Verifique e tente novamente.")

    return name, authentication_status, username


def require_authentication(
    config_path: Path | None = None,
) -> stauth.Authenticate | None:
    """Guarda global a ser chamada no topo de ``app.py``.

    Se o usuário não estiver autenticado, renderiza o fluxo de login e
    retorna ``None`` — o chamador deve então chamar ``st.stop()`` para
    não exibir o restante da aplicação. Se autenticado, devolve o
    ``Authenticate`` para que o app possa renderizar o botão de logout.

    Args:
        config_path: caminho alternativo do ``config.yaml`` (útil em testes).

    Returns:
        ``Authenticate`` se já autenticado; ``None`` se o login está
        pendente (banner, lockout ou formulário ainda não submetido).
    """

    authenticator = build_authenticator(config_path=config_path)
    _, authentication_status, _ = render_login(authenticator)

    if authentication_status is True:
        return authenticator
    return None
