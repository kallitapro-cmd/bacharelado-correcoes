"""Corretor Acadêmico — entrypoint Streamlit.

A autenticação (Story 1.2) atua como guarda global: nenhuma tela do app é
exibida antes do login bem-sucedido, conforme AC #1.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from src.auth.authenticator import require_authentication
from src.utils import audit_log

st.set_page_config(
    page_title="Corretor Acadêmico",
    page_icon="📝",
    layout="wide",
)

# --- Startup check de configuração (Story 1.3) -----------------------------
#
# A chave da API Anthropic é obrigatória para qualquer correção.
# Verificamos ANTES da autenticação para que o PA enxergue imediatamente
# que a configuração de deploy está incompleta, em vez de tropeçar no
# login e nunca descobrir a causa raiz.
#
# Apenas a presença da chave é validada — o valor não é logado nem
# exibido (ADR-004: API key nunca aparece em logs/UI).
_anthropic_api_key = st.secrets.get("ANTHROPIC_API_KEY", None)
if not _anthropic_api_key:
    st.error(
        "ANTHROPIC_API_KEY não configurada. "
        "No Streamlit Cloud, acesse Settings > Secrets e adicione sua "
        "chave da Anthropic. Em desenvolvimento local, copie "
        "`.streamlit/secrets.toml.example` para `.streamlit/secrets.toml` "
        "e preencha o valor. Consulte `docs/guides/deploy.md` para o "
        "passo a passo completo."
    )
    st.stop()

# --- Guarda de autenticação (Story 1.2) ------------------------------------
#
# Todo conteúdo após este bloco só é renderizado para PAs autenticados.
authenticator = require_authentication()
if authenticator is None:
    # Login pendente (banner LGPD, lockout ou formulário não submetido).
    st.stop()

# --- App propriamente dita -------------------------------------------------
identificacao_pa = st.session_state.get("identificacao_pa", "")

with st.sidebar:
    st.markdown(f"**PA:** {identificacao_pa or '(não informado)'}")
    authenticator.logout("Sair", location="sidebar")

    # --- Audit log de sessão (Story 1.12) ----------------------------------
    #
    # Download do log permite ao PA obter o registro das ações executadas
    # nesta sessão antes do encerramento (retenção zero conforme ADR-004).
    st.divider()
    st.download_button(
        label="Baixar log da sessão",
        data=audit_log.get_csv(),
        file_name=f"audit-log-{datetime.now().strftime('%Y%m%d-%H%M')}.csv",
        mime="text/csv",
        help=(
            "Download do log de auditoria da sessão atual (CSV). "
            "O log é descartado ao encerrar a sessão."
        ),
    )

st.title("Corretor Acadêmico")
st.info(
    "Corretor Acadêmico — em construção. As demais funcionalidades serão "
    "introduzidas nas stories seguintes do Sprint 1."
)
