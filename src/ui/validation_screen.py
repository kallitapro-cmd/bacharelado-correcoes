"""Tela de validação do batch (Story 3.2).

Implementa a Tela 3 do fluxo do PA — tabela de validação interativa com
Progressive Disclosure em 3 níveis:

- Level 0 (tabela): RA + notas + Δ + badge status + ícones de alerta
- Level 1 (painel por aluno): razao_confianca + feedback + botões de decisão
- Level 2 (sub-painel): pares de plágio OU detalhes de grupo

Garantia inegociável (ADR-006): detecção de plágio/grupos é **informativa**.
Toda decisão de nota é do PA.

Consome ``st.session_state["batch_results"]`` (gravado pela Story 3.1).
Grava ``st.session_state["decisoes"]`` (consumido pela Story 3.3).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import streamlit as st

if TYPE_CHECKING:
    from packages.wrapper.schemas import FichaCorrecao

    from src.batch.group_detector import GrupoCandidato
    from src.batch.plagiarism_detector import ParPlagio

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

#: Limiar de severidade severa de plágio (AC-02)
LIMIAR_PLAGIO_SEVERO = 0.85
#: Limiar mínimo de alerta de plágio (moderado)
LIMIAR_PLAGIO_MODERADO = 0.70

#: Opções do filtro rápido (AC-03)
FILTROS_DISPONIVEIS = ["Todos", "Com alertas", "Top 10%", "Cap 9", "Normal"]


# ---------------------------------------------------------------------------
# Funções puras de lógica (testáveis sem Streamlit)
# ---------------------------------------------------------------------------


def construir_linha_aluno(
    ficha: FichaCorrecao,
    alertas_plagio: list[ParPlagio],
    grupos_candidatos: list[GrupoCandidato],
) -> dict[str, Any]:
    """Monta dicionário com todos os dados de uma linha da tabela (AC-01).

    Returns dict com chaves: ra, nota_bruta, nota_calibrada, delta,
    status_badge, icones_alerta, tem_plagio_severo, tem_plagio_moderado,
    tem_grupo, pares_plagio, grupos_do_aluno, feedback.
    """
    ra = ficha.ra
    # nota_a1 é a nota calibrada (calibrador faz model_copy(update={"nota_a1": ...}))
    # nota_a2 é a nota bruta original quando disponível; None quando o batch só tem A1
    nota_calibrada = ficha.nota_a1 if ficha.nota_a1 is not None else 0.0
    nota_bruta = ficha.nota_a2 if ficha.nota_a2 is not None else nota_calibrada

    delta = nota_calibrada - nota_bruta

    # Status badge (cap 9 = nota calibrada == 9.0 e foi aplicado cap)
    status_badge = "Normal"
    if nota_calibrada > 9.0:
        status_badge = "Top 10%"
    elif nota_calibrada == 9.0 and nota_bruta > 9.0:
        status_badge = "Cap 9"

    # Alertas de plágio relacionados a este RA
    pares_do_aluno: list[ParPlagio] = [
        p for p in alertas_plagio if p.aluno_a == ra or p.aluno_b == ra
    ]

    tem_plagio_severo = any(p.similaridade >= LIMIAR_PLAGIO_SEVERO for p in pares_do_aluno)
    tem_plagio_moderado = any(
        LIMIAR_PLAGIO_MODERADO <= p.similaridade < LIMIAR_PLAGIO_SEVERO for p in pares_do_aluno
    )

    # Grupos relacionados a este RA
    grupos_do_aluno: list[GrupoCandidato] = [g for g in grupos_candidatos if ra in g.membros]
    tem_grupo = len(grupos_do_aluno) > 0

    # Ícones em ordem de gravidade (AC-02)
    icones: list[str] = []
    if tem_plagio_severo:
        icones.append("🔴")
        # Severo subsume moderado — não exibe 🟡 se há 🔴
    elif tem_plagio_moderado:
        icones.append("🟡")
    if tem_grupo:
        icones.append("👥")

    return {
        "ra": ra,
        "nota_bruta": nota_bruta,
        "nota_calibrada": nota_calibrada,
        "delta": delta,
        "status_badge": status_badge,
        "icones_alerta": icones,
        "tem_alerta": bool(icones),
        "tem_plagio_severo": tem_plagio_severo,
        "tem_plagio_moderado": tem_plagio_moderado,
        "tem_grupo": tem_grupo,
        "pares_plagio": pares_do_aluno,
        "grupos_do_aluno": grupos_do_aluno,
        "feedback": ficha.feedback,
        "confianca_nivel": ficha.confianca,
        "razao_confianca": _calcular_razao_confianca_numerica(ficha.confianca),
    }


def _calcular_razao_confianca_numerica(confianca: str) -> float:
    """Converte nível textual de confiança em percentual numérico (0.0–1.0)."""
    mapa = {"alta": 0.90, "media": 0.65, "baixa": 0.40}
    return mapa.get(confianca, 0.65)


def aplicar_filtro(
    linhas: list[dict[str, Any]],
    filtro: str,
) -> list[dict[str, Any]]:
    """Filtra linhas da tabela conforme seleção do PA (AC-03)."""
    if filtro == "Todos":
        return linhas
    if filtro == "Com alertas":
        return [row for row in linhas if row["tem_alerta"]]
    if filtro == "Top 10%":
        return [row for row in linhas if row["status_badge"] == "Top 10%"]
    if filtro == "Cap 9":
        return [row for row in linhas if row["status_badge"] == "Cap 9"]
    if filtro == "Normal":
        return [row for row in linhas if row["status_badge"] == "Normal"]
    return linhas


def calcular_alunos_sem_alertas_pendentes(
    linhas: list[dict[str, Any]],
    decisoes: dict[str, Any],
) -> list[dict[str, Any]]:
    """Retorna linhas de alunos sem alertas que ainda não foram decididos (AC-05)."""
    return [row for row in linhas if not row["tem_alerta"] and row["ra"] not in decisoes]


def calcular_alertas_pendentes(
    linhas: list[dict[str, Any]],
    decisoes: dict[str, Any],
) -> list[dict[str, Any]]:
    """Retorna linhas com alertas sem nenhuma decisão registrada (AC-14)."""
    return [row for row in linhas if row["tem_alerta"] and row["ra"] not in decisoes]


def exportacao_liberada(
    linhas: list[dict[str, Any]],
    decisoes: dict[str, Any],
) -> bool:
    """Retorna True quando todos os alunos com alertas têm decisão (AC-14)."""
    return len(calcular_alertas_pendentes(linhas, decisoes)) == 0


def registrar_decisao(
    ra: str,
    acao: str,
    nota_final: float,
    observacao: str = "",
) -> dict[str, Any]:
    """Cria entrada de decisão para ``st.session_state['decisoes']`` (AC-12)."""
    return {
        "acao": acao,
        "nota_final": nota_final,
        "timestamp": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(),
        "observacao": observacao,
    }


def resumo_contagens(
    linhas: list[dict[str, Any]],
    decisoes: dict[str, Any],
) -> dict[str, int]:
    """Retorna contagens agregadas para sidebar (AC-16) e botão export (AC-15)."""
    aprovados = sum(
        1 for ra, d in decisoes.items() if d.get("acao") in ("aprovado", "aprovado_lote")
    )
    editados = sum(1 for ra, d in decisoes.items() if d.get("acao") == "editado")
    revisao_manual = sum(1 for ra, d in decisoes.items() if d.get("acao") == "revisao_manual")
    alertas_pendentes = len(calcular_alertas_pendentes(linhas, decisoes))

    return {
        "total": len(linhas),
        "aprovados": aprovados,
        "editados": editados,
        "revisao_manual": revisao_manual,
        "alertas_pendentes": alertas_pendentes,
        "lotes_com_erro": 0,
    }


# ---------------------------------------------------------------------------
# Componentes de renderização
# ---------------------------------------------------------------------------


def _badge_delta(delta: float) -> str:
    """Formata delta com cor via markdown syntax do Streamlit (AC-07)."""
    sinal = "+" if delta > 0 else ""
    valor = f"{sinal}{delta:.1f}"
    if delta > 0:
        return f":green[{valor}]"
    if delta < 0:
        return f":red[{valor}]"
    return f":gray[{valor}]"


def _badge_status(status: str) -> str:
    """Formata badge de status com cor."""
    if status == "Top 10%":
        return ":blue[⭐ Top 10%]"
    if status == "Cap 9":
        return ":orange[🔒 Cap 9]"
    return ":gray[Normal]"


def _badge_confianca(razao: float) -> str:
    """Formata badge de confiança (AC-07 — sem HTML customizado)."""
    pct = int(razao * 100)
    if razao < 0.60:
        return f":red[{pct}%]"
    if razao < 0.80:
        return f":orange[{pct}%]"
    return f":green[{pct}%]"


def _renderizar_level2_plagio(
    linha: dict[str, Any],
    key_prefix: str,
) -> None:
    """Renderiza detalhes de plágio no Level 2 (AC-08, AC-10)."""
    pares = linha["pares_plagio"]
    ra = linha["ra"]

    pares_visiveis = [p for p in pares if p.similaridade >= LIMIAR_PLAGIO_MODERADO]
    pares_suprimidos_todos: list[tuple[str, str, float]] = []
    for grupo in linha["grupos_do_aluno"]:
        for ra_a, ra_b, sim in grupo.pares_suprimidos:
            if ra_a == ra or ra_b == ra:
                pares_suprimidos_todos.append((ra_a, ra_b, sim))

    if pares_visiveis:
        st.markdown("**Pares com alerta:**")
        for par in sorted(pares_visiveis, key=lambda p: p.similaridade, reverse=True):
            ra_par = par.aluno_b if par.aluno_a == ra else par.aluno_a
            badge = "🔴" if par.similaridade >= LIMIAR_PLAGIO_SEVERO else "🟡"
            st.markdown(f"- {badge} RA `{ra_par}` — similaridade **{par.similaridade:.0%}**")

    # AC-10: pares descartados (abaixo do threshold)
    if pares_suprimidos_todos:
        n_sup = len(pares_suprimidos_todos)
        st.caption(f"{n_sup} par(es) descartado(s) (abaixo do limiar de 70%)")
        if st.toggle(
            "Ver pares descartados",
            key=f"{key_prefix}_sup_toggle",
            value=False,
        ):
            for ra_a, ra_b, sim in pares_suprimidos_todos:
                ra_par = ra_b if ra_a == ra else ra_a
                st.markdown(
                    f"<span style='color:gray'>RA `{ra_par}` — {sim:.0%}</span>",
                    unsafe_allow_html=True,
                )


def _renderizar_level2_grupo(
    linha: dict[str, Any],
    key_prefix: str,
) -> None:
    """Renderiza detalhes de grupo no Level 2 (AC-09)."""
    for i, grupo in enumerate(linha["grupos_do_aluno"]):
        st.markdown(f"**Grupo candidato #{i + 1}**")
        st.markdown(f"- **Membros:** {', '.join(sorted(grupo.membros))}")
        st.markdown(f"- **Confiança:** `{grupo.confianca}`")
        if grupo.razao_confianca:
            st.markdown(f"- **Razão:** {grupo.razao_confianca}")


def _renderizar_level1(
    linha: dict[str, Any],
    key_prefix: str,
) -> None:
    """Renderiza painel de revisão Level 1 (AC-06, AC-07, AC-11, AC-13b)."""
    ra = linha["ra"]
    decisoes: dict[str, Any] = st.session_state.setdefault("decisoes", {})

    # Confiança visual (AC-07)
    razao = linha["razao_confianca"]
    st.progress(razao, text=None)
    st.markdown(
        f"**Confiança da correção:** {_badge_confianca(razao)}",
    )

    # Feedback resumido
    st.markdown(
        f"**Feedback do squad:** {linha['feedback'][:300]}{'...' if len(linha['feedback']) > 300 else ''}"
    )

    st.markdown("---")

    # Level 2 — plágio e grupo (AC-08, AC-09)
    col_l2a, col_l2b = st.columns(2)
    with col_l2a:
        tem_plagio = linha["tem_plagio_severo"] or linha["tem_plagio_moderado"]
        if tem_plagio and st.toggle(
            "Ver detalhes de plágio",
            key=f"{key_prefix}_det_plagio",
            value=False,
        ):
            _renderizar_level2_plagio(linha, key_prefix)
    with col_l2b:
        if linha["tem_grupo"] and st.toggle(
            "Ver detalhes de grupo",
            key=f"{key_prefix}_det_grupo",
            value=False,
        ):
            _renderizar_level2_grupo(linha, key_prefix)

    st.markdown("---")

    # Botões de decisão
    if ra in decisoes:
        acao_atual = decisoes[ra].get("acao", "")
        nota_final = decisoes[ra].get("nota_final", linha["nota_calibrada"])
        if acao_atual == "revisao_manual":
            st.markdown("🔲 **Pendente** — marcado para revisão manual")
        elif acao_atual == "editado":
            st.markdown(f"✏️ **Nota editada:** {nota_final:.1f}")
        else:
            st.markdown(f"✓ **Aprovado** (nota: {nota_final:.1f})")
        if st.button("Desfazer decisão", key=f"{key_prefix}_desfazer_l1"):
            del decisoes[ra]
            st.rerun()
    else:
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            if st.button("✓ Manter nota", key=f"{key_prefix}_manter", use_container_width=True):
                decisoes[ra] = registrar_decisao(
                    ra=ra,
                    acao="aprovado",
                    nota_final=linha["nota_calibrada"],
                )
                st.session_state["revisando"][ra] = False
                st.rerun()
        with col_b:
            if st.button("✏️ Editar nota", key=f"{key_prefix}_editar_btn", use_container_width=True):
                st.session_state[f"_editando_{ra}"] = True
                st.rerun()
        with col_c:
            if st.button("✗ Revisão manual", key=f"{key_prefix}_manual", use_container_width=True):
                decisoes[ra] = registrar_decisao(
                    ra=ra,
                    acao="revisao_manual",
                    nota_final=linha["nota_calibrada"],
                )
                st.session_state["revisando"][ra] = False
                st.rerun()

        # Edição inline (AC-11)
        if st.session_state.get(f"_editando_{ra}", False):
            nova_nota = st.number_input(
                "Nova nota",
                min_value=0.0,
                max_value=10.0,
                value=float(linha["nota_calibrada"]),
                step=0.1,
                format="%.1f",
                key=f"{key_prefix}_nota_input",
            )
            col_conf, col_canc = st.columns(2)
            with col_conf:
                if st.button("Confirmar edição", key=f"{key_prefix}_conf_edit"):
                    decisoes[ra] = registrar_decisao(
                        ra=ra,
                        acao="editado",
                        nota_final=nova_nota,
                    )
                    st.session_state[f"_editando_{ra}"] = False
                    st.session_state["revisando"][ra] = False
                    st.rerun()
            with col_canc:
                if st.button("Cancelar", key=f"{key_prefix}_canc_edit"):
                    st.session_state[f"_editando_{ra}"] = False
                    st.rerun()

    # Campo observações (AC-13b)
    obs_key = f"{key_prefix}_obs"
    obs_atual = decisoes.get(ra, {}).get("observacao", "")
    nova_obs = st.text_area(
        "Observações",
        value=obs_atual,
        placeholder="Anotações para a coordenação...",
        key=obs_key,
        height=80,
    )
    if nova_obs != obs_atual and ra in decisoes:
        decisoes[ra]["observacao"] = nova_obs


def _renderizar_linha_tabela(
    linha: dict[str, Any],
    key_prefix: str,
) -> None:
    """Renderiza uma linha da tabela de validação (AC-04)."""
    ra = linha["ra"]
    decisoes: dict[str, Any] = st.session_state.setdefault("decisoes", {})
    revisando: dict[str, bool] = st.session_state.setdefault("revisando", {})

    with st.container():
        col_ra, col_nb, col_nc, col_delta, col_st, col_al, col_acao = st.columns(
            [2, 1.5, 1.5, 1.2, 1.5, 1.5, 2]
        )

        col_ra.markdown(f"`{ra}`")
        col_nb.markdown(f"{linha['nota_bruta']:.1f}")
        col_nc.markdown(f"**{linha['nota_calibrada']:.1f}**")
        col_delta.markdown(_badge_delta(linha["delta"]))
        col_st.markdown(_badge_status(linha["status_badge"]))
        col_al.markdown(" ".join(linha["icones_alerta"]) if linha["icones_alerta"] else "—")

        with col_acao:
            if ra in decisoes:
                acao = decisoes[ra].get("acao", "")
                if acao == "revisao_manual":
                    st.markdown("🔲 Pendente")
                else:
                    nota_final = decisoes[ra].get("nota_final", linha["nota_calibrada"])
                    st.markdown(f"✓ Aprovado ({nota_final:.1f})")
                if st.button("Desfazer", key=f"{key_prefix}_desfazer", use_container_width=True):
                    del decisoes[ra]
                    st.rerun()
            elif linha["tem_alerta"]:
                rotulo = "👁 Revisar" if not revisando.get(ra, False) else "▲ Fechar"
                if st.button(rotulo, key=f"{key_prefix}_revisar", use_container_width=True):
                    revisando[ra] = not revisando.get(ra, False)
                    st.rerun()
            else:
                if st.button("✓ Aprovar", key=f"{key_prefix}_aprovar", use_container_width=True):
                    decisoes[ra] = registrar_decisao(
                        ra=ra,
                        acao="aprovado",
                        nota_final=linha["nota_calibrada"],
                    )
                    st.rerun()

    # Painel Level 1 — renderizado via st.container, NÃO st.expander (AC-04)
    if revisando.get(ra, False) and ra not in decisoes:
        with st.container(border=True):
            _renderizar_level1(linha, key_prefix)

    st.divider()


# ---------------------------------------------------------------------------
# Componente Streamlit principal
# ---------------------------------------------------------------------------


def render() -> None:
    """Renderiza a tela de validação.

    Chamada por ``pages/3_validacao.py``.
    """
    st.title("Corretor Acadêmico — Validação do batch")
    st.markdown("---")

    # Valida batch_results
    batch_results = st.session_state.get("batch_results")
    if not batch_results:
        st.error("Resultados do batch ausentes. Execute o processamento (Tela 2) antes de validar.")
        return

    fichas_calibradas: list[FichaCorrecao] = batch_results.get("fichas_calibradas", [])
    alertas_plagio: list[ParPlagio] = batch_results.get("alertas_plagio", [])
    grupos_candidatos: list[GrupoCandidato] = batch_results.get("grupos_candidatos", [])

    if not fichas_calibradas:
        st.warning("Nenhuma ficha calibrada encontrada.")
        return

    # ---------------------------------------------------------------------------
    # Inicializa estado preservado entre reruns (AC-18)
    # ---------------------------------------------------------------------------
    if "decisoes" not in st.session_state:
        st.session_state["decisoes"] = {}
    if "revisando" not in st.session_state:
        st.session_state["revisando"] = {}
    if "filtro_ativo" not in st.session_state:
        st.session_state["filtro_ativo"] = "Todos"

    decisoes: dict[str, Any] = st.session_state["decisoes"]

    # ---------------------------------------------------------------------------
    # Constrói linhas
    # ---------------------------------------------------------------------------
    linhas = [
        construir_linha_aluno(ficha, alertas_plagio, grupos_candidatos)
        for ficha in fichas_calibradas
    ]

    # ---------------------------------------------------------------------------
    # Sidebar — Zone A (AC-16)
    # ---------------------------------------------------------------------------
    contagens = resumo_contagens(linhas, decisoes)
    with st.sidebar:
        st.subheader("Resumo da validação")
        st.metric("Total de alunos", contagens["total"])
        st.metric("Aprovados", contagens["aprovados"] + contagens["editados"])
        st.metric("Alertas pendentes", contagens["alertas_pendentes"])
        lotes_com_erro = int(batch_results.get("lotes_com_erro", 0))
        if lotes_com_erro:
            st.metric("Lotes com erro", lotes_com_erro)

    # ---------------------------------------------------------------------------
    # Filtro rápido (AC-03, AC-18)
    # ---------------------------------------------------------------------------
    filtro_selecionado = st.radio(
        "Filtrar por:",
        FILTROS_DISPONIVEIS,
        index=FILTROS_DISPONIVEIS.index(st.session_state["filtro_ativo"]),
        horizontal=True,
        key="_filtro_radio",
    )
    if filtro_selecionado != st.session_state["filtro_ativo"]:
        st.session_state["filtro_ativo"] = filtro_selecionado
        st.rerun()

    linhas_filtradas = aplicar_filtro(linhas, filtro_selecionado)

    # ---------------------------------------------------------------------------
    # Batch approval (AC-05)
    # ---------------------------------------------------------------------------
    sem_alertas_pendentes = calcular_alunos_sem_alertas_pendentes(linhas, decisoes)
    if sem_alertas_pendentes:
        n_batch = len(sem_alertas_pendentes)
        if not st.session_state.get("_confirmando_batch", False):
            if st.button(
                f"✓ Aprovar todos os {n_batch} alunos sem alertas",
                type="secondary",
            ):
                st.session_state["_confirmando_batch"] = True
                st.rerun()
        else:
            st.warning(f"Confirmar aprovação de {n_batch} alunos sem alertas?")
            col_conf, col_canc = st.columns(2)
            with col_conf:
                if st.button("Confirmar", type="primary", key="_batch_confirmar"):
                    for candidato in sem_alertas_pendentes:
                        decisoes[candidato["ra"]] = registrar_decisao(
                            ra=candidato["ra"],
                            acao="aprovado_lote",
                            nota_final=candidato["nota_calibrada"],
                        )
                    st.session_state["_confirmando_batch"] = False
                    st.success(f"{n_batch} alunos aprovados em lote")
                    st.rerun()
            with col_canc:
                if st.button("Cancelar", key="_batch_cancelar"):
                    st.session_state["_confirmando_batch"] = False
                    st.rerun()

    st.markdown("---")

    # ---------------------------------------------------------------------------
    # Cabeçalho da tabela
    # ---------------------------------------------------------------------------
    col_h = st.columns([2, 1.5, 1.5, 1.2, 1.5, 1.5, 2])
    cabecalhos = ["RA", "Nota Bruta", "Nota Calibrada", "Δ", "Status", "Alertas", "Ação"]
    for col, cab in zip(col_h, cabecalhos, strict=True):
        col.markdown(f"**{cab}**")
    st.divider()

    # ---------------------------------------------------------------------------
    # Linhas da tabela (AC-04)
    # ---------------------------------------------------------------------------
    for idx, linha in enumerate(linhas_filtradas):
        _renderizar_linha_tabela(linha, key_prefix=f"row_{idx}_{linha['ra']}")

    # ---------------------------------------------------------------------------
    # Controle de exportação (AC-14, AC-15)
    # ---------------------------------------------------------------------------
    st.markdown("---")
    alertas_pend = calcular_alertas_pendentes(linhas, decisoes)
    if alertas_pend:
        n_pend = len(alertas_pend)
        st.error(
            f"{n_pend} aluno(s) com alertas aguardando decisão (Aprovar / Editar / Revisão manual)"
        )
        st.button("Exportar para Excel", disabled=True, type="primary")
    else:
        contagens_final = resumo_contagens(linhas, decisoes)
        ap = contagens_final["aprovados"]
        ed = contagens_final["editados"]
        rv = contagens_final["revisao_manual"]
        st.success(
            f"Pronto para exportar — {ap} aprovados, {ed} editados, "
            f"{rv} marcados para revisão manual"
        )
        if st.button("Exportar para Excel", type="primary"):
            st.info("Exportação será implementada na Story 3.3.")
