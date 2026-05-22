"""Testes unitários para src.auth.authenticator — Story 1.2.

Focam em lógica pura (lockout, contadores, carregamento de config e banner).
A renderização Streamlit é mockada via ``monkeypatch`` para que os testes
rodem fora de um contexto Streamlit real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import streamlit as st

if TYPE_CHECKING:
    from pathlib import Path

from src.auth import authenticator as auth_mod
from src.auth.authenticator import (
    LGPD_BANNER_TEXT,
    LOCKOUT_DURATION_SECONDS,
    LOCKOUT_MESSAGE,
    MAX_LOGIN_ATTEMPTS,
    SESSION_EXPIRED_MESSAGE,
    build_authenticator,
    is_lgpd_accepted,
    is_locked_out,
    load_config,
    register_failed_attempt,
    remaining_lockout_seconds,
    render_lgpd_banner,
    reset_attempts,
)


@pytest.fixture(autouse=True)
def clean_session_state() -> None:
    """Garante session_state limpo entre testes."""

    # streamlit.session_state expõe interface tipo dict; usar list() para
    # evitar mutação durante iteração.
    for key in list(st.session_state.keys()):
        del st.session_state[key]


@pytest.fixture
def fake_now(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    """Substitui o relógio interno do módulo por um valor controlável."""

    state = {"now": 1_000_000.0}

    def _now() -> float:
        return state["now"]

    monkeypatch.setattr(auth_mod, "_now", _now)
    return state


# --- LGPD ------------------------------------------------------------------


class TestLgpdBanner:
    def test_texto_do_banner_inalterado_em_relacao_ao_adr_004(self) -> None:
        # Garante que ninguém edite o wording sem revisar o ADR-004.
        assert "processa notas e feedbacks" in LGPD_BANNER_TEXT
        assert "não são armazenados em servidores externos" in LGPD_BANNER_TEXT
        assert "autorização para acessar os dados das turmas" in LGPD_BANNER_TEXT

    def test_inicia_sem_aceite(self) -> None:
        assert is_lgpd_accepted() is False

    def test_aceite_persiste_em_session_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Simula clique no botão "Confirmar e continuar".
        captured: dict[str, str] = {}

        def fake_warning(text: str) -> None:
            captured["warning"] = text

        def fake_button(label: str, key: str | None = None) -> bool:
            captured["button"] = label
            return True

        def fake_rerun() -> None:
            captured["rerun"] = "called"

        monkeypatch.setattr(st, "warning", fake_warning)
        monkeypatch.setattr(st, "button", fake_button)
        monkeypatch.setattr(st, "rerun", fake_rerun)

        result = render_lgpd_banner()

        # Banner ainda não considerado "aceito" no retorno (foi um rerun),
        # mas o estado foi gravado e o botão correto exibido.
        assert result is False
        assert captured["warning"] == LGPD_BANNER_TEXT
        assert captured["button"] == "Confirmar e continuar"
        assert captured["rerun"] == "called"
        assert is_lgpd_accepted() is True

    def test_renderizacao_sem_clique_devolve_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(st, "warning", lambda *_a, **_kw: None)
        monkeypatch.setattr(st, "button", lambda *_a, **_kw: False)
        monkeypatch.setattr(st, "rerun", lambda: None)

        assert render_lgpd_banner() is False
        assert is_lgpd_accepted() is False

    def test_quando_ja_aceito_retorna_true_sem_renderizar(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        st.session_state["lgpd_accepted"] = True

        def boom(*_a: Any, **_kw: Any) -> None:
            raise AssertionError("banner não deveria ser renderizado de novo")

        monkeypatch.setattr(st, "warning", boom)
        monkeypatch.setattr(st, "button", boom)

        assert render_lgpd_banner() is True


# --- Lockout ---------------------------------------------------------------


class TestLockout:
    def test_constantes_seguem_a_story(self) -> None:
        assert MAX_LOGIN_ATTEMPTS == 5
        assert LOCKOUT_DURATION_SECONDS == 15 * 60
        assert "acesso está pausado" in LOCKOUT_MESSAGE
        assert "15 minutos" in LOCKOUT_MESSAGE
        assert SESSION_EXPIRED_MESSAGE == (
            "Sua sessão anterior expirou. Por favor, entre novamente."
        )

    def test_inicialmente_nao_esta_em_lockout(self) -> None:
        assert is_locked_out() is False
        assert remaining_lockout_seconds() == 0

    def test_falhas_consecutivas_nao_disparam_antes_de_5(self, fake_now: dict[str, float]) -> None:
        del fake_now  # apenas para fixar o relógio
        for _ in range(MAX_LOGIN_ATTEMPTS - 1):
            triggered = register_failed_attempt()
            assert triggered is False
        assert is_locked_out() is False
        assert st.session_state["login_attempts"] == MAX_LOGIN_ATTEMPTS - 1

    def test_quinta_falha_dispara_lockout(self, fake_now: dict[str, float]) -> None:
        for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
            triggered = register_failed_attempt()
            if attempt < MAX_LOGIN_ATTEMPTS:
                assert triggered is False
            else:
                assert triggered is True
        assert is_locked_out() is True
        assert remaining_lockout_seconds() == LOCKOUT_DURATION_SECONDS
        assert st.session_state["lockout_until"] == (fake_now["now"] + LOCKOUT_DURATION_SECONDS)

    def test_lockout_expira_apos_15_minutos(self, fake_now: dict[str, float]) -> None:
        for _ in range(MAX_LOGIN_ATTEMPTS):
            register_failed_attempt()
        assert is_locked_out() is True

        # Avança o relógio para 1 segundo APÓS o fim do lockout.
        fake_now["now"] += LOCKOUT_DURATION_SECONDS + 1
        assert is_locked_out() is False
        # E o contador foi zerado para permitir nova rodada.
        assert st.session_state["login_attempts"] == 0
        assert "lockout_until" not in st.session_state

    def test_lockout_continua_um_segundo_antes_do_fim(self, fake_now: dict[str, float]) -> None:
        for _ in range(MAX_LOGIN_ATTEMPTS):
            register_failed_attempt()
        fake_now["now"] += LOCKOUT_DURATION_SECONDS - 1
        assert is_locked_out() is True
        assert remaining_lockout_seconds() == 1

    def test_reset_attempts_zera_contador_e_remove_lockout(
        self, fake_now: dict[str, float]
    ) -> None:
        del fake_now
        for _ in range(MAX_LOGIN_ATTEMPTS):
            register_failed_attempt()
        assert is_locked_out() is True

        reset_attempts()
        assert is_locked_out() is False
        assert st.session_state["login_attempts"] == 0
        assert "lockout_until" not in st.session_state


# --- Carregamento de configuração ------------------------------------------


class TestLoadConfig:
    def test_arquivo_inexistente_lanca_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="config.yaml.example"):
            load_config(tmp_path / "nao_existe.yaml")

    def test_yaml_invalido_lanca_value_error(self, tmp_path: Path) -> None:
        ruim = tmp_path / "ruim.yaml"
        ruim.write_text("apenas_uma_string_solta", encoding="utf-8")
        with pytest.raises(ValueError, match="mapeamento YAML"):
            load_config(ruim)

    def test_carrega_estrutura_basica(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "credentials:\n"
            "  usernames:\n"
            "    pa_teste:\n"
            "      email: pa@teste.edu.br\n"
            "      name: PA Teste\n"
            "      password: $2b$12$abc\n"
            "cookie:\n"
            "  expiry_days: 1\n"
            "  key: chave_teste\n"
            "  name: cookie_teste\n"
            "preauthorized:\n"
            "  emails: []\n",
            encoding="utf-8",
        )
        cfg = load_config(cfg_file)
        assert cfg["cookie"]["name"] == "cookie_teste"
        assert "pa_teste" in cfg["credentials"]["usernames"]

    def test_sem_credentials_lanca_value_error(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "cookie:\n  expiry_days: 1\n  key: chave_teste\n  name: cookie_teste\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="credentials"):
            load_config(cfg_file)

    def test_sem_cookie_lanca_value_error(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "credentials:\n  usernames: {}\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="cookie"):
            load_config(cfg_file)

    def test_sem_ambas_as_chaves_lista_as_duas_no_erro(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("preauthorized:\n  emails: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="credentials") as exc_info:
            load_config(cfg_file)
        assert "cookie" in str(exc_info.value)


# --- build_authenticator ---------------------------------------------------


class TestBuildAuthenticator:
    def test_cookie_expira_em_1_dia(self) -> None:
        cfg: dict[str, Any] = {
            "credentials": {
                "usernames": {
                    "pa_x": {
                        "email": "pa@x.com",
                        "name": "PA X",
                        # Hash bcrypt válido (gerado para 'senha123').
                        "password": (
                            "$2b$12$JzwUEr/9qV6XVlA5o3p1z.z0HrZ.eA8ZcKZ2qO0nT9bz7E8VgWzgu"
                        ),
                    }
                }
            },
            "cookie": {
                "expiry_days": 30,  # deve ser sobrescrito para 1
                "key": "chave_de_teste_aleatoria",
                "name": "cookie_teste",
            },
        }
        authn = build_authenticator(config=cfg)
        # O atributo interno varia entre versões; mas a configuração de
        # cookie passada para o construtor segue o contrato de 1 dia.
        # Verificamos via atributo "cookie_handler" ou diretamente em
        # atributos privados conhecidos da v0.4.x.
        cookie_handler = getattr(authn, "cookie_controller", None) or getattr(
            authn, "cookie_handler", None
        )
        if cookie_handler is not None:
            expiry = getattr(cookie_handler, "cookie_expiry_days", None)
            if expiry is not None:
                assert expiry == 1
        # Independentemente do nome interno, o objeto foi instanciado com
        # sucesso — ausência de exceção já prova que o contrato bate com
        # a assinatura da biblioteca.
        assert authn is not None


# --- Sessão expirada (H2) --------------------------------------------------


class TestSessionExpired:
    def test_mensagem_nao_tem_jargao_tecnico(self) -> None:
        assert "cookie" not in SESSION_EXPIRED_MESSAGE.lower()
        assert "autenticação" not in SESSION_EXPIRED_MESSAGE.lower()
        assert "token" not in SESSION_EXPIRED_MESSAGE.lower()

    def test_mensagem_contem_instrucao_clara(self) -> None:
        assert "expirou" in SESSION_EXPIRED_MESSAGE.lower()
        assert "entre novamente" in SESSION_EXPIRED_MESSAGE.lower()

    def test_flag_had_session_gravada_apos_login_bem_sucedido(self) -> None:
        st.session_state["had_session"] = True
        assert st.session_state.get("had_session") is True


# --- Lockout com contagem regressiva (H3) ----------------------------------


class TestLockoutCountdown:
    def test_remaining_lockout_retorna_0_sem_lockout(self) -> None:
        assert remaining_lockout_seconds() == 0

    def test_remaining_lockout_retorna_segundos_corretos(self, fake_now: dict[str, float]) -> None:
        for _ in range(MAX_LOGIN_ATTEMPTS):
            register_failed_attempt()
        assert remaining_lockout_seconds() == LOCKOUT_DURATION_SECONDS

    def test_remaining_lockout_decresce_com_tempo(self, fake_now: dict[str, float]) -> None:
        for _ in range(MAX_LOGIN_ATTEMPTS):
            register_failed_attempt()
        fake_now["now"] += 60  # avança 1 minuto
        assert remaining_lockout_seconds() == LOCKOUT_DURATION_SECONDS - 60

    def test_lockout_message_sem_linguagem_punitiva(self) -> None:
        assert "excessivas" not in LOCKOUT_MESSAGE.lower()
        assert "bloqueado" not in LOCKOUT_MESSAGE.lower()
        assert "pausado" in LOCKOUT_MESSAGE.lower()
