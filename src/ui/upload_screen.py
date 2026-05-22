"""Tela de upload e configuração do batch (Story 3.0).

Implementa a Tela 1 do fluxo do PA:
- Zone A: upload da planilha + preview das primeiras 5 linhas
- Zone B: enunciado do trabalho + metadados opcionais (turma, professor, data_prova)
- Zone C: estimativa de custo em BRL + botão "Iniciar correção"

Garante ADR-004: `nome` do aluno NÃO entra no dict `alunos` enviado ao batch.
Nomes são preservados em `st.session_state["nomes_por_ra"]` exclusivamente
para o preview local e para a exportação Excel (Story 3.3).
"""

from __future__ import annotations

import datetime
from typing import Any

import pandas as pd
import streamlit as st
from packages.wrapper.clone_client import BATCH_SIZE

from src.batch.batch_processor import estimar_custo_brl

# ---------------------------------------------------------------------------
# Constantes de validação
# ---------------------------------------------------------------------------

COLUNAS_OBRIGATORIAS = {"ra", "nome", "resposta"}
COLUNAS_OPCIONAIS = {"turma"}

_MAX_COST_FALLBACK = 15.0


# ---------------------------------------------------------------------------
# Funções puras (testáveis sem Streamlit)
# ---------------------------------------------------------------------------


def validar_colunas(df: pd.DataFrame) -> list[str]:
    """Retorna lista de colunas obrigatórias ausentes no DataFrame.

    Comparação case-insensitive: normaliza nomes de coluna para minúsculas.
    """
    colunas_df = {c.strip().lower() for c in df.columns}
    return sorted(COLUNAS_OBRIGATORIAS - colunas_df)


def normalizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    """Renomeia colunas para minúsculas e strip de espaços."""
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    return df


def construir_alunos(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Extrai lista de dicts `{ra, turma, resposta}` — sem `nome` (ADR-004).

    `turma` é preservada no dict de alunos pois é metadado não-PII.
    `nome` é excluído intencionalmente.
    """
    tem_turma = "turma" in df.columns
    alunos = []
    for _, row in df.iterrows():
        aluno: dict[str, Any] = {
            "ra": str(row["ra"]).strip(),
            "resposta": str(row["resposta"]).strip(),
            "turma": str(row["turma"]).strip() if tem_turma else "",
        }
        alunos.append(aluno)
    return alunos


def construir_nomes_por_ra(df: pd.DataFrame) -> dict[str, str]:
    """Constrói mapa `{ra: nome}` para uso exclusivo em preview e exportação Excel."""
    if "nome" not in df.columns:
        return {}
    return {str(row["ra"]).strip(): str(row["nome"]).strip() for _, row in df.iterrows()}


def calcular_estimativa(n_alunos: int) -> float:
    """Calcula estimativa de custo BRL para N alunos."""
    if n_alunos <= 0:
        return 0.0
    import math

    n_lotes = math.ceil(n_alunos / BATCH_SIZE)
    return estimar_custo_brl(n_lotes=n_lotes)


def obter_max_cost() -> float:
    """Lê MAX_COST_BRL de st.secrets com fallback 15.0."""
    try:
        return float(st.secrets.get("MAX_COST_BRL", str(_MAX_COST_FALLBACK)))
    except Exception:  # noqa: BLE001
        return _MAX_COST_FALLBACK


def validar_pode_iniciar(
    df_valido: bool,
    enunciado: str,
    custo: float,
    max_cost: float,
) -> tuple[bool, str]:
    """Retorna (pode_iniciar, motivo_bloqueio).

    Motivo vazio indica que pode iniciar.
    """
    if not df_valido:
        return False, "Planilha inválida ou não carregada."
    if not enunciado.strip():
        return False, "Enunciado do trabalho é obrigatório."
    if custo > max_cost:
        return False, f"Estimativa R$ {custo:.2f} excede limite R$ {max_cost:.2f}."
    return True, ""


# ---------------------------------------------------------------------------
# Componente Streamlit principal
# ---------------------------------------------------------------------------


def render() -> None:
    """Renderiza a tela de upload e configuração.

    Chamada pela página principal do app Streamlit.
    """
    st.title("Corretor Acadêmico — Upload e Configuração")
    st.markdown("---")

    # -----------------------------------------------------------------------
    # Zone A — Upload do arquivo + preview
    # -----------------------------------------------------------------------
    st.subheader("1. Planilha de alunos")

    arquivo = st.file_uploader(
        "Selecione a planilha da turma",
        type=["xlsx", "xls"],
        help="Formato aceito: .xlsx ou .xls. Colunas obrigatórias: ra, nome, resposta.",
    )

    df: pd.DataFrame | None = None
    df_valido = False
    n_alunos = 0

    if arquivo is not None:
        # Validação de extensão redundante (st.file_uploader já filtra,
        # mas mantemos para testes e robustez)
        nome_arquivo = arquivo.name.lower()
        if not (nome_arquivo.endswith(".xlsx") or nome_arquivo.endswith(".xls")):
            st.error(f"Arquivo '{arquivo.name}' não é uma planilha válida. Aceitos: .xlsx ou .xls")
        else:
            try:
                df_raw = pd.read_excel(arquivo, engine="openpyxl")
                df = normalizar_colunas(df_raw)
                ausentes = validar_colunas(df)

                if ausentes:
                    st.error(
                        f"Colunas obrigatórias ausentes: **{', '.join(ausentes)}**. "
                        "Verifique o cabeçalho da planilha."
                    )
                else:
                    df_valido = True
                    n_alunos = len(df)
                    st.success(f"Planilha carregada: **{n_alunos} alunos**")

                    # Preview — exibe nome (PII) só aqui, nunca em session_state["alunos"]
                    colunas_preview = [
                        c for c in ["ra", "nome", "turma", "resposta"] if c in df.columns
                    ]
                    st.dataframe(df[colunas_preview].head(5), use_container_width=True)

            except Exception as exc:  # noqa: BLE001
                st.error(f"Erro ao ler a planilha: {exc}")

    # -----------------------------------------------------------------------
    # Zone B — Enunciado + metadados opcionais
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("2. Enunciado do trabalho")

    enunciado = st.text_area(
        "Enunciado do trabalho",
        max_chars=2000,
        placeholder="Cole aqui o enunciado completo do trabalho avaliado...",
        help="Máximo 2000 caracteres. O enunciado orienta os critérios de correção.",
    )

    st.markdown("---")
    st.subheader("3. Metadados (opcionais)")

    col1, col2, col3 = st.columns(3)
    with col1:
        turma = st.text_input("Turma", placeholder="Ex: CC2025A")
    with col2:
        professor = st.text_input("Professor(a)", placeholder="Ex: Prof. Silva")
    with col3:
        data_prova = st.date_input(
            "Data da prova",
            value=None,
            format="DD/MM/YYYY",
        )

    # -----------------------------------------------------------------------
    # Zone C — Estimativa de custo + botão
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("4. Estimativa de custo e confirmação")

    custo = calcular_estimativa(n_alunos)
    max_cost = obter_max_cost()

    pode_iniciar, motivo = validar_pode_iniciar(df_valido, enunciado, custo, max_cost)

    # Exibe estimativa sempre que há alunos carregados
    if n_alunos > 0:
        col_custo, col_limite = st.columns(2)
        with col_custo:
            st.metric("Estimativa de custo", f"R$ {custo:.2f}")
        with col_limite:
            st.metric("Limite configurado", f"R$ {max_cost:.2f}")

        if custo > max_cost:
            st.warning(
                f"A estimativa **R$ {custo:.2f}** excede o limite "
                f"configurado de **R$ {max_cost:.2f}**. "
                "Aumente `MAX_COST_BRL` em st.secrets ou reduza o número de alunos."
            )
    else:
        st.info("Carregue a planilha para ver a estimativa de custo.")

    # Botão principal — desabilitado enquanto pré-condições não forem satisfeitas
    if st.button(
        "Iniciar correção",
        disabled=not pode_iniciar,
        type="primary",
        use_container_width=True,
        help=motivo if not pode_iniciar else "Iniciar o processamento em batch.",
    ):
        assert df is not None  # garantido por pode_iniciar
        alunos = construir_alunos(df)
        nomes_por_ra = construir_nomes_por_ra(df)

        metadata: dict[str, Any] = {
            "turma": turma or "",
            "professor": professor or "",
            "data_prova": data_prova.isoformat() if isinstance(data_prova, datetime.date) else None,
        }

        st.session_state["batch_config"] = {
            "alunos": alunos,
            "enunciado": enunciado.strip(),
            "metadata": metadata,
        }
        st.session_state["nomes_por_ra"] = nomes_por_ra

        st.switch_page("pages/2_progresso.py")
