"""Tela de exportação para Excel (Story 3.3).

Implementa a Tela 4 do fluxo do PA — exportação final para planilha institucional.

Fluxo:
- Zone A (topo): resumo de conferência (AC-07)
- Zone B (centro): preview das primeiras 10 linhas
- Zone C (rodapé): download button + link para recomeçar

Consome:
- ``st.session_state["decisoes"]`` (Story 3.2)
- ``st.session_state["batch_results"]`` (Story 3.1)
- ``st.session_state["nomes_por_ra"]`` (Story 3.0)
- ``st.session_state["batch_config"]["metadata"]`` (Story 3.0)

Geração 100% local — sem chamadas API externas (ADR-004, AC-08).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from src.ui.excel_builder import construir_workbook, gerar_nome_arquivo, workbook_para_bytes
from src.ui.validation_screen import resumo_contagens


def _validar_pre_condicoes() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Verifica session_state mínimo (AC-01). Retorna (batch_results, decisoes) ou (None, None)."""
    decisoes = st.session_state.get("decisoes")
    batch_results = st.session_state.get("batch_results")

    if not decisoes or not batch_results:
        st.error(
            "Dados de validação ausentes. "
            "Complete a revisão na tela de validação antes de exportar."
        )
        st.page_link("pages/3_validacao.py", label="← Voltar à validação")
        return None, None

    return batch_results, decisoes


def render() -> None:
    """Renderiza a tela de exportação.

    Chamada por ``pages/4_exportacao.py``.
    """
    st.title("Corretor Acadêmico — Exportar para Excel")
    st.markdown("---")

    # AC-01 — Verificar pré-condições
    batch_results, decisoes = _validar_pre_condicoes()
    if batch_results is None or decisoes is None:
        return

    fichas_calibradas = batch_results.get("fichas_calibradas", [])
    alertas_plagio = batch_results.get("alertas_plagio", [])
    grupos_candidatos = batch_results.get("grupos_candidatos", [])

    nomes_por_ra: dict[str, str] = st.session_state.get("nomes_por_ra", {})
    batch_config = st.session_state.get("batch_config", {})
    metadata: dict[str, Any] = batch_config.get("metadata", {})

    # ---------------------------------------------------------------------------
    # Zone A — Resumo de conferência (AC-07)
    # ---------------------------------------------------------------------------
    linhas_mock = [
        {"ra": f.ra, "tem_alerta": False, "status_badge": "Normal"} for f in fichas_calibradas
    ]
    contagens = resumo_contagens(linhas_mock, decisoes)

    st.subheader("Resumo de conferência")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total de alunos", contagens["total"])
    col2.metric("Aprovados", contagens["aprovados"])
    col3.metric("Editados", contagens["editados"])
    col4.metric("Revisão manual", contagens["revisao_manual"])
    lotes_erro = int(batch_results.get("lotes_com_erro", 0))
    col5.metric("Lotes com erro", lotes_erro)

    st.markdown("---")

    # ---------------------------------------------------------------------------
    # Zone B — Preview das primeiras 10 linhas (design Alan Nicolas)
    # ---------------------------------------------------------------------------
    st.subheader("Preview (primeiras 10 linhas)")
    fichas_preview = fichas_calibradas[:10]
    if fichas_preview:
        preview_rows = []
        for f in fichas_preview:
            nota_calib = float(f.nota_a1) if f.nota_a1 is not None else 0.0
            nota_bruta = float(f.nota_a2) if f.nota_a2 is not None else nota_calib
            decisao = decisoes.get(f.ra, {})
            nota_final = float(decisao.get("nota_final", nota_calib))
            acao = decisao.get("acao", "")
            revisao_manual = acao == "revisao_manual"
            preview_rows.append(
                {
                    "RA": f.ra,
                    "Nome": nomes_por_ra.get(f.ra, ""),
                    "Nota Bruta": round(nota_bruta, 1),
                    "Nota Calibrada": round(nota_calib, 1),
                    "Nota Final": round(nota_final, 1),
                    "Revisão Manual": revisao_manual,
                }
            )

        import pandas as pd  # noqa: PLC0415

        df_preview = pd.DataFrame(preview_rows)
        st.dataframe(df_preview, use_container_width=True, hide_index=True)
        if len(fichas_calibradas) > 10:
            st.caption(f"Exibindo 10 de {len(fichas_calibradas)} alunos.")

    st.markdown("---")

    # ---------------------------------------------------------------------------
    # Zone C — Download button (AC-06)
    # ---------------------------------------------------------------------------
    turma = str(metadata.get("turma", ""))
    nome_arquivo = gerar_nome_arquivo(turma, datetime.now())

    st.subheader("Download")
    st.info(
        f"O arquivo **{nome_arquivo}** será gerado com 2 abas: "
        f"**Notas** (dados principais) e **Alertas** (plágio e grupos)."
    )

    if st.button("Gerar e baixar Excel", type="primary"):
        with st.spinner("Gerando arquivo..."):
            wb = construir_workbook(
                fichas_calibradas=fichas_calibradas,
                alertas_plagio=alertas_plagio,
                grupos_candidatos=grupos_candidatos,
                decisoes=decisoes,
                nomes_por_ra=nomes_por_ra,
                metadata=metadata,
            )
            excel_bytes = workbook_para_bytes(wb)

        st.download_button(
            label=f"⬇ Baixar {nome_arquivo}",
            data=excel_bytes,
            file_name=nome_arquivo,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
        st.success("Arquivo gerado com sucesso.")

    st.markdown("---")

    # Opção de recomeçar (design Alan Nicolas)
    if st.button("← Corrigir mais alunos (nova sessão)"):
        for key in [
            "batch_results",
            "decisoes",
            "batch_config",
            "nomes_por_ra",
            "revisando",
            "filtro_ativo",
            "_confirmando_batch",
        ]:
            st.session_state.pop(key, None)
        st.rerun()
