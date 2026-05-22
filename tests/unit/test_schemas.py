"""Testes unitários dos schemas Pydantic — Story 1.9.

Cobertura dos 6 ACs:
    AC1 — import de FichaCorrecao e RespostaBatch sem erro
    AC2 — FichaCorrecao valida ra, feedback, flags, confianca
    AC3 — Validador de RA rejeita != 11 dígitos após strip
    AC4 — RespostaBatch aceita lista vazia de fichas
    AC5 — pytest tests/unit/test_schemas.py passa
    AC6 — Schema consistente com ADR-002 (mesmos campos/tipos/constraints)

Correções pré-QA (Pedro Valério):
    PV1 — Aluno.ra com validação de formato idêntica a FichaCorrecao.ra
    PV2 — ArquivoConvertido.flags tipado com FlagCorrecao
    PV3 — RespostaBatchIA com min_length=1 (fronteira IA→app)
    PV4 — ArquivoConvertido.metodo_extracao com Literal enum
    PV5 — EstadoBatch.data_aula com validator ISO/BR → normaliza para ISO
    PV6 — FichaCorrecao.feedback strip + min_length=1 real
    PV7 — ResultadoLote.custo_usd ge=0.0
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.schemas import (
    Aluno,
    ArquivoConvertido,
    EstadoBatch,
    FichaCorrecao,
    MatrizPontuacao,
    RespostaBatch,
    RespostaBatchIA,
    ResultadoLote,
)

# ---------------------------------------------------------------------------
# AC1 — Imports funcionam sem erro
# ---------------------------------------------------------------------------


class TestImportsAC1:
    def test_import_ficha_correcao(self) -> None:
        assert FichaCorrecao is not None

    def test_import_resposta_batch(self) -> None:
        assert RespostaBatch is not None

    def test_modelos_adicionais_disponiveis(self) -> None:
        assert all(
            modelo is not None
            for modelo in (
                Aluno,
                ArquivoConvertido,
                MatrizPontuacao,
                ResultadoLote,
                EstadoBatch,
            )
        )


# ---------------------------------------------------------------------------
# AC2 — FichaCorrecao valida campos obrigatórios
# ---------------------------------------------------------------------------


class TestFichaCorrecaoAC2:
    def test_aceita_ficha_minima_valida(self) -> None:
        ficha = FichaCorrecao(
            ra="12345678901",
            feedback="Feedback do aluno",
            confianca="alta",
        )
        assert ficha.ra == "12345678901"
        assert ficha.feedback == "Feedback do aluno"
        assert ficha.confianca == "alta"
        assert ficha.flags == []
        assert ficha.nota_a1 is None
        assert ficha.nota_a2 is None
        assert ficha.matriz_pontuacao is None

    def test_aceita_ficha_completa(self) -> None:
        ficha = FichaCorrecao(
            ra="12345678901",
            nota_a1=8.5,
            nota_a2=9.0,
            matriz_pontuacao=MatrizPontuacao(
                criterio_apresentacao=8.0,
                criterio_conteudo=9.0,
                criterio_metodologia=7.5,
                criterio_conclusao=8.5,
            ),
            feedback="Excelente trabalho",
            flags=["ia_generativa"],
            confianca="media",
        )
        assert ficha.nota_a1 == 8.5
        assert ficha.matriz_pontuacao is not None
        assert ficha.matriz_pontuacao.criterio_apresentacao == 8.0
        assert ficha.flags == ["ia_generativa"]

    def test_ra_obrigatorio(self) -> None:
        with pytest.raises(ValidationError):
            FichaCorrecao(feedback="x", confianca="alta")  # type: ignore[call-arg]

    def test_feedback_obrigatorio(self) -> None:
        with pytest.raises(ValidationError):
            FichaCorrecao(ra="12345678901", confianca="alta")  # type: ignore[call-arg]

    def test_feedback_nao_pode_ser_vazio(self) -> None:
        with pytest.raises(ValidationError):
            FichaCorrecao(ra="12345678901", feedback="", confianca="alta")

    def test_confianca_obrigatoria(self) -> None:
        with pytest.raises(ValidationError):
            FichaCorrecao(ra="12345678901", feedback="ok")  # type: ignore[call-arg]

    @pytest.mark.parametrize("confianca", ["alta", "media", "baixa"])
    def test_confianca_aceita_valores_permitidos(self, confianca: str) -> None:
        ficha = FichaCorrecao(ra="12345678901", feedback="ok", confianca=confianca)  # type: ignore[arg-type]
        assert ficha.confianca == confianca

    @pytest.mark.parametrize("confianca_invalida", ["ALTA", "muito alta", "medium", "", "x"])
    def test_confianca_rejeita_valor_invalido(self, confianca_invalida: str) -> None:
        with pytest.raises(ValidationError):
            FichaCorrecao(
                ra="12345678901",
                feedback="ok",
                confianca=confianca_invalida,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "flag",
        ["plagio", "ia_generativa", "arquivo_errado", "sem_vinculo"],
    )
    def test_flags_aceita_valores_do_enum(self, flag: str) -> None:
        ficha = FichaCorrecao(
            ra="12345678901",
            feedback="ok",
            confianca="alta",
            flags=[flag],  # type: ignore[list-item]
        )
        assert ficha.flags == [flag]

    def test_flags_rejeita_valor_fora_do_enum(self) -> None:
        with pytest.raises(ValidationError):
            FichaCorrecao(
                ra="12345678901",
                feedback="ok",
                confianca="alta",
                flags=["valor_invalido"],  # type: ignore[list-item]
            )

    def test_flags_default_e_lista_vazia(self) -> None:
        ficha = FichaCorrecao(ra="12345678901", feedback="ok", confianca="alta")
        assert ficha.flags == []

    @pytest.mark.parametrize("nota", [-0.1, 10.1, 11.0, -1.0])
    def test_nota_fora_de_intervalo_rejeitada(self, nota: float) -> None:
        with pytest.raises(ValidationError):
            FichaCorrecao(
                ra="12345678901",
                feedback="ok",
                confianca="alta",
                nota_a1=nota,
            )

    @pytest.mark.parametrize("nota", [0.0, 5.5, 10.0])
    def test_nota_dentro_do_intervalo_aceita(self, nota: float) -> None:
        ficha = FichaCorrecao(
            ra="12345678901",
            feedback="ok",
            confianca="alta",
            nota_a1=nota,
        )
        assert ficha.nota_a1 == nota


# ---------------------------------------------------------------------------
# AC3 — Validador de RA (regex 11 dígitos após strip)
# ---------------------------------------------------------------------------


class TestValidadorRaAC3:
    def test_ra_com_11_digitos_e_aceito(self) -> None:
        ficha = FichaCorrecao(ra="12345678901", feedback="ok", confianca="alta")
        assert ficha.ra == "12345678901"

    def test_ra_com_espacos_e_normalizado(self) -> None:
        ficha = FichaCorrecao(ra="  12345678901  ", feedback="ok", confianca="alta")
        assert ficha.ra == "12345678901"

    @pytest.mark.parametrize(
        "ra_invalido",
        [
            "1234567890",  # 10 dígitos
            "123456789012",  # 12 dígitos
            "",  # vazio
            "abcdefghijk",  # 11 não-dígitos
            "1234567890a",  # mistura
            "123 45678901",  # espaço interno
        ],
    )
    def test_ra_invalido_rejeitado(self, ra_invalido: str) -> None:
        with pytest.raises(ValidationError):
            FichaCorrecao(ra=ra_invalido, feedback="ok", confianca="alta")

    def test_ra_apenas_espacos_rejeitado(self) -> None:
        with pytest.raises(ValidationError):
            FichaCorrecao(ra="   ", feedback="ok", confianca="alta")

    def test_ra_com_quebra_de_linha_normalizada(self) -> None:
        ficha = FichaCorrecao(ra="\n12345678901\n", feedback="ok", confianca="alta")
        assert ficha.ra == "12345678901"


# ---------------------------------------------------------------------------
# AC4 — RespostaBatch aceita lista vazia
# ---------------------------------------------------------------------------


class TestRespostaBatchAC4:
    def test_lista_vazia_e_aceita(self) -> None:
        resposta = RespostaBatch()
        assert resposta.fichas == []
        assert resposta.observacoes_gerais is None

    def test_lista_vazia_explicita(self) -> None:
        resposta = RespostaBatch(fichas=[])
        assert resposta.fichas == []

    def test_aceita_uma_ficha(self) -> None:
        ficha = FichaCorrecao(ra="12345678901", feedback="ok", confianca="alta")
        resposta = RespostaBatch(fichas=[ficha], observacoes_gerais="tudo certo")
        assert len(resposta.fichas) == 1
        assert resposta.observacoes_gerais == "tudo certo"

    def test_aceita_multiplas_fichas(self) -> None:
        fichas = [
            FichaCorrecao(ra=f"1234567890{n}", feedback="ok", confianca="alta") for n in range(3)
        ]
        resposta = RespostaBatch(fichas=fichas)
        assert len(resposta.fichas) == 3


# ---------------------------------------------------------------------------
# AC6 — Consistência com ADR-002
# ---------------------------------------------------------------------------


class TestConsistenciaAdr002AC6:
    """Verifica que os schemas refletem o ADR-002 com fidelidade."""

    def test_ficha_correcao_tem_todos_campos_adr002(self) -> None:
        campos_esperados = {
            "ra",
            "nota_a1",
            "nota_a2",
            "matriz_pontuacao",
            "feedback",
            "flags",
            "confianca",
        }
        assert set(FichaCorrecao.model_fields.keys()) == campos_esperados

    def test_matriz_pontuacao_tem_quatro_criterios(self) -> None:
        campos_esperados = {
            "criterio_apresentacao",
            "criterio_conteudo",
            "criterio_metodologia",
            "criterio_conclusao",
        }
        assert set(MatrizPontuacao.model_fields.keys()) == campos_esperados

    def test_resposta_batch_campos_adr002(self) -> None:
        campos_esperados = {"fichas", "observacoes_gerais"}
        assert set(RespostaBatch.model_fields.keys()) == campos_esperados

    def test_ficha_aceita_serializacao_round_trip(self) -> None:
        original = FichaCorrecao(
            ra="12345678901",
            nota_a1=7.0,
            feedback="ok",
            flags=["plagio"],
            confianca="baixa",
        )
        json_str = original.model_dump_json()
        recriada = FichaCorrecao.model_validate_json(json_str)
        assert recriada == original


# ---------------------------------------------------------------------------
# Modelos adicionais (smoke tests)
# ---------------------------------------------------------------------------


class TestModelosAuxiliares:
    def test_aluno_minimo(self) -> None:
        aluno = Aluno(ra="12345678901", nome="Fulano")
        assert aluno.email is None
        assert aluno.telefone is None

    def test_arquivo_convertido(self) -> None:
        arq = ArquivoConvertido(
            ra="12345678901",
            nome_arquivo="ficha.pdf",
            texto="conteudo extraido",
            metodo_extracao="nativo",
        )
        assert arq.flags == []
        assert arq.metodo_extracao == "nativo"

    def test_resultado_lote_default(self) -> None:
        lote = ResultadoLote(lote_num=1)
        assert lote.fichas == []
        assert lote.custo_usd == 0.0
        assert lote.status == "pendente"

    @pytest.mark.parametrize(
        "status",
        ["pendente", "processando", "concluido", "erro"],
    )
    def test_resultado_lote_status_validos(self, status: str) -> None:
        lote = ResultadoLote(lote_num=1, status=status)  # type: ignore[arg-type]
        assert lote.status == status

    def test_estado_batch_default(self) -> None:
        estado = EstadoBatch(
            disciplina="Matematica",
            data_aula="2026-05-22",
            atividade="A1",
        )
        assert estado.alunos == []
        assert estado.lotes == []
        assert estado.status_geral == "configurando"

    @pytest.mark.parametrize(
        "status",
        ["configurando", "processando", "revisao", "exportado"],
    )
    def test_estado_batch_status_validos(self, status: str) -> None:
        estado = EstadoBatch(
            disciplina="Matematica",
            data_aula="2026-05-22",
            atividade="A1",
            status_geral=status,  # type: ignore[arg-type]
        )
        assert estado.status_geral == status


# ---------------------------------------------------------------------------
# PV1 — Aluno.ra com validação de formato (VETO crítico)
# ---------------------------------------------------------------------------


class TestAlunoRaValidacaoPV1:
    def test_ra_valido_aceito(self) -> None:
        aluno = Aluno(ra="12345678901", nome="Fulano")
        assert aluno.ra == "12345678901"

    def test_ra_com_espacos_normalizado(self) -> None:
        aluno = Aluno(ra="  12345678901  ", nome="Fulano")
        assert aluno.ra == "12345678901"

    def test_ra_com_quebra_de_linha_normalizado(self) -> None:
        aluno = Aluno(ra="\n12345678901\n", nome="Fulano")
        assert aluno.ra == "12345678901"

    @pytest.mark.parametrize(
        "ra_invalido",
        [
            "1234567890",  # 10 dígitos
            "123456789012",  # 12 dígitos
            "",  # vazio
            "abcdefghijk",  # letras
            "1234567890a",  # mistura
            "123 45678901",  # espaço interno
            "23.045.678-9",  # formato com pontos/hífen (planilha)
        ],
    )
    def test_ra_invalido_rejeitado(self, ra_invalido: str) -> None:
        with pytest.raises(ValidationError):
            Aluno(ra=ra_invalido, nome="Fulano")

    def test_aluno_ra_tem_mesma_constraint_que_ficha_correcao(self) -> None:
        # Valida comportamento equivalente: o mesmo RA inválido deve falhar nos dois models.
        ra_invalido = "23.045.678-9"
        with pytest.raises(ValidationError):
            Aluno(ra=ra_invalido, nome="Fulano")
        with pytest.raises(ValidationError):
            FichaCorrecao(ra=ra_invalido, feedback="ok", confianca="alta")


# ---------------------------------------------------------------------------
# PV2 — ArquivoConvertido.flags tipado com FlagCorrecao (VETO crítico)
# ---------------------------------------------------------------------------


class TestArquivoConvertidoFlagsPV2:
    def test_flags_aceita_valores_do_enum(self) -> None:
        for flag in ("plagio", "ia_generativa", "arquivo_errado", "sem_vinculo"):
            arq = ArquivoConvertido(
                ra="12345678901",
                nome_arquivo="f.pdf",
                texto="x",
                metodo_extracao="nativo",
                flags=[flag],  # type: ignore[list-item]
            )
            assert arq.flags == [flag]

    def test_flags_rejeita_string_livre(self) -> None:
        with pytest.raises(ValidationError):
            ArquivoConvertido(
                ra="12345678901",
                nome_arquivo="f.pdf",
                texto="x",
                metodo_extracao="nativo",
                flags=["corrupto"],  # type: ignore[list-item]
            )

    def test_flags_default_lista_vazia(self) -> None:
        arq = ArquivoConvertido(
            ra="12345678901",
            nome_arquivo="f.pdf",
            texto="x",
            metodo_extracao="nativo",
        )
        assert arq.flags == []


# ---------------------------------------------------------------------------
# PV3 — RespostaBatchIA com min_length=1 (VETO crítico)
# ---------------------------------------------------------------------------


class TestRespostaBatchIAPV3:
    def test_aceita_ao_menos_uma_ficha(self) -> None:
        ficha = FichaCorrecao(ra="12345678901", feedback="ok", confianca="alta")
        resposta = RespostaBatchIA(fichas=[ficha])
        assert len(resposta.fichas) == 1

    def test_rejeita_lista_vazia(self) -> None:
        with pytest.raises(ValidationError):
            RespostaBatchIA(fichas=[])

    def test_aceita_multiplas_fichas(self) -> None:
        fichas = [
            FichaCorrecao(ra=f"1234567890{n}", feedback="ok", confianca="alta") for n in range(3)
        ]
        resposta = RespostaBatchIA(fichas=fichas)
        assert len(resposta.fichas) == 3

    def test_observacoes_gerais_opcional(self) -> None:
        ficha = FichaCorrecao(ra="12345678901", feedback="ok", confianca="alta")
        resposta = RespostaBatchIA(fichas=[ficha], observacoes_gerais="tudo ok")
        assert resposta.observacoes_gerais == "tudo ok"

    def test_resposta_batch_interna_ainda_aceita_lista_vazia(self) -> None:
        """RespostaBatch (estado interno) NÃO deve ser afetado pelo min_length=1."""
        resposta = RespostaBatch(fichas=[])
        assert resposta.fichas == []


# ---------------------------------------------------------------------------
# PV4 — ArquivoConvertido.metodo_extracao com Literal (médio)
# ---------------------------------------------------------------------------


class TestMetodoExtracaoPV4:
    @pytest.mark.parametrize("metodo", ["nativo", "ocr", "misto", "nenhum"])
    def test_aceita_metodos_validos(self, metodo: str) -> None:
        arq = ArquivoConvertido(
            ra="12345678901",
            nome_arquivo="f.pdf",
            texto="x",
            metodo_extracao=metodo,  # type: ignore[arg-type]
        )
        assert arq.metodo_extracao == metodo

    @pytest.mark.parametrize(
        "metodo_invalido",
        ["PDF_NATIVO", "auto", "manual", "", "tesseract"],
    )
    def test_rejeita_metodos_invalidos(self, metodo_invalido: str) -> None:
        with pytest.raises(ValidationError):
            ArquivoConvertido(
                ra="12345678901",
                nome_arquivo="f.pdf",
                texto="x",
                metodo_extracao=metodo_invalido,  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# PV5 — EstadoBatch.data_aula validação e normalização (médio)
# ---------------------------------------------------------------------------


class TestDataAulaPV5:
    def test_aceita_formato_iso(self) -> None:
        estado = EstadoBatch(disciplina="Mat", data_aula="2026-05-22", atividade="A1")
        assert estado.data_aula == "2026-05-22"

    def test_aceita_formato_br_e_normaliza_para_iso(self) -> None:
        estado = EstadoBatch(disciplina="Mat", data_aula="22/05/2026", atividade="A1")
        assert estado.data_aula == "2026-05-22"

    @pytest.mark.parametrize(
        "data_invalida",
        [
            "quinta-feira",
            "22-05-2026",  # formato com hífens mas ordem BR
            "2026/05/22",  # separador errado em ISO
            "20260522",  # sem separadores
            "",
            "32/01/2026",  # dia inválido
            "01/13/2026",  # mês inválido
        ],
    )
    def test_rejeita_formatos_invalidos(self, data_invalida: str) -> None:
        with pytest.raises(ValidationError):
            EstadoBatch(disciplina="Mat", data_aula=data_invalida, atividade="A1")

    def test_espacos_em_data_br_normalizados(self) -> None:
        estado = EstadoBatch(disciplina="Mat", data_aula="  22/05/2026  ", atividade="A1")
        assert estado.data_aula == "2026-05-22"

    def test_espacos_em_data_iso_normalizados(self) -> None:
        estado = EstadoBatch(disciplina="Mat", data_aula="  2026-05-22  ", atividade="A1")
        assert estado.data_aula == "2026-05-22"


# ---------------------------------------------------------------------------
# PV6 — FichaCorrecao.feedback strip + rejeita whitespace-only (baixo)
# ---------------------------------------------------------------------------


class TestFeedbackStripPV6:
    def test_feedback_com_espacos_e_normalizado(self) -> None:
        ficha = FichaCorrecao(ra="12345678901", feedback="  ok  ", confianca="alta")
        assert ficha.feedback == "ok"

    def test_feedback_so_espacos_rejeitado(self) -> None:
        with pytest.raises(ValidationError):
            FichaCorrecao(ra="12345678901", feedback="   ", confianca="alta")

    def test_feedback_so_tabs_e_newlines_rejeitado(self) -> None:
        with pytest.raises(ValidationError):
            FichaCorrecao(ra="12345678901", feedback="\t\n", confianca="alta")

    def test_feedback_vazio_rejeitado(self) -> None:
        with pytest.raises(ValidationError):
            FichaCorrecao(ra="12345678901", feedback="", confianca="alta")


# ---------------------------------------------------------------------------
# PV7 — ResultadoLote.custo_usd ge=0.0 (baixo)
# ---------------------------------------------------------------------------


class TestCustoUsdPV7:
    def test_custo_zero_aceito(self) -> None:
        lote = ResultadoLote(lote_num=1, custo_usd=0.0)
        assert lote.custo_usd == 0.0

    def test_custo_positivo_aceito(self) -> None:
        lote = ResultadoLote(lote_num=1, custo_usd=1.23)
        assert lote.custo_usd == 1.23

    def test_custo_negativo_rejeitado(self) -> None:
        with pytest.raises(ValidationError):
            ResultadoLote(lote_num=1, custo_usd=-0.01)
