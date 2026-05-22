"""Testes unitários do calibrador estatístico de notas (Story 2.3).

Cobertura mínima exigida pela story (TC-CAL-01 a TC-CAL-06) + casos de
guarda adicionais (batch vazio, resposta malformada do Sonnet).

Convenções:

* O ``client`` Anthropic é sempre mockado via ``MagicMock`` — nenhuma
  chamada real à API é feita.
* As fichas mock usam :class:`FichaCorrecao` real (Pydantic) para
  garantir compatibilidade com o ``model_copy`` usado no calibrador.
* ``log_action`` é silenciado via ``contextlib.suppress`` no próprio
  calibrador; quando precisamos auditá-lo, mockamos diretamente.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from packages.wrapper.schemas import FichaCorrecao

import src.batch.calibrator as cal
from src.batch.calibrator import (
    API_TIMEOUT,
    MAX_TOKENS_CALIBRACAO,
    MODELO_CALIBRACAO,
    TEMPERATURE_CALIBRACAO,
    calibrar_batch,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ra(i: int) -> str:
    """Gera RA de 11 dígitos (formato Story 1.x — ADR-001)."""
    return f"2026{i:07d}"


def _ficha(i: int, nota: float | None) -> FichaCorrecao:
    """Cria :class:`FichaCorrecao` com valores mínimos válidos."""
    return FichaCorrecao(
        ra=_ra(i),
        nota_a1=nota,
        feedback="Feedback de teste.",
        confianca="alta",
        flags=[],
    )


def _mock_response_ranking(fichas: list[FichaCorrecao]) -> SimpleNamespace:
    """Mock de resposta da API que ecoa o ranking sem alterar notas brutas.

    Simula o comportamento do Sonnet quando ele já recebe um payload
    ``no_top=True/False`` correto e não precisa de ajustes adicionais —
    devolve a mesma nota bruta para cada RA.
    """
    payload = {
        "ranking": [
            {
                "ra": f.ra,
                "nota_ajustada": f.nota_a1 if f.nota_a1 is not None else 0.0,
            }
            for f in fichas
        ]
    }
    return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))])


def _mock_client(response: SimpleNamespace) -> MagicMock:
    """Mock de ``anthropic.Anthropic()`` com ``messages.create`` espionável."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = MagicMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# TC-CAL-01 — top 10% com N=10 (top_n=1), nota mais alta preservada
# ---------------------------------------------------------------------------


def test_tc_cal_01_top_10_com_n_10():
    """Com N=10 (top_n=1) o aluno de maior nota mantém >9.0, demais caem a 9.0."""
    fichas = [
        _ficha(1, 9.8),  # top (única)
        _ficha(2, 9.5),  # cap → 9.0
        _ficha(3, 9.3),  # cap → 9.0
        _ficha(4, 9.1),  # cap → 9.0
        _ficha(5, 8.7),  # mantém
        _ficha(6, 8.0),  # mantém
        _ficha(7, 7.5),  # mantém
        _ficha(8, 7.0),  # mantém
        _ficha(9, 6.5),  # mantém
        _ficha(10, 5.0),  # mantém
    ]
    client = _mock_client(_mock_response_ranking(fichas))

    resultado = calibrar_batch(fichas, {"turma": "T1"}, client=client)

    # ordem preservada
    assert len(resultado) == 10
    assert resultado[0].ra == _ra(1)
    # RA-001 com nota 9.8 preservada (está no top)
    assert resultado[0].nota_a1 == pytest.approx(9.8)
    # RA-002, RA-003, RA-004 com nota > 9.0 caíram a 9.0
    assert resultado[1].nota_a1 == pytest.approx(9.0)
    assert resultado[2].nota_a1 == pytest.approx(9.0)
    assert resultado[3].nota_a1 == pytest.approx(9.0)
    # alunos com nota <= 9.0 ficam inalterados
    assert resultado[4].nota_a1 == pytest.approx(8.7)
    assert resultado[9].nota_a1 == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# TC-CAL-02 — cap 9 aplicado para alunos fora do top (N=20)
# ---------------------------------------------------------------------------


def test_tc_cal_02_cap_9_aplicado_fora_do_top():
    """N=20 → top_n=2; 3 alunos fora do top com nota > 9.0 são todos reduzidos."""
    fichas = [
        _ficha(1, 9.9),  # top (2 maiores)
        _ficha(2, 9.8),  # top
        _ficha(3, 9.5),  # FORA do top → 9.0
        _ficha(4, 9.2),  # FORA do top → 9.0
        _ficha(5, 9.1),  # FORA do top → 9.0
        *[_ficha(i, 7.0) for i in range(6, 21)],  # 15 alunos com 7.0
    ]
    assert len(fichas) == 20
    client = _mock_client(_mock_response_ranking(fichas))

    resultado = calibrar_batch(fichas, {}, client=client)

    # Mapeia RA → nota_final
    por_ra = {f.ra: f.nota_a1 for f in resultado}

    # Top (RA-001, RA-002) mantém notas brutas (>9.0 permitido)
    assert por_ra[_ra(1)] == pytest.approx(9.9)
    assert por_ra[_ra(2)] == pytest.approx(9.8)
    # Fora do top com nota >9.0 → reduzidos a 9.0
    assert por_ra[_ra(3)] == pytest.approx(9.0)
    assert por_ra[_ra(4)] == pytest.approx(9.0)
    assert por_ra[_ra(5)] == pytest.approx(9.0)
    # Outros inalterados
    for i in range(6, 21):
        assert por_ra[_ra(i)] == pytest.approx(7.0)


# ---------------------------------------------------------------------------
# TC-CAL-03 — empate no limiar do top (ambos entram)
# ---------------------------------------------------------------------------


def test_tc_cal_03_empate_no_limiar_inclui_todos():
    """N=10, RA-001 e RA-002 com nota 9.7 (empate no topo) — ambos no top."""
    fichas = [
        _ficha(1, 9.7),  # empate no top
        _ficha(2, 9.7),  # empate no top
        _ficha(3, 9.4),  # FORA → cap 9.0
        *[_ficha(i, 7.0) for i in range(4, 11)],
    ]
    assert len(fichas) == 10
    client = _mock_client(_mock_response_ranking(fichas))

    resultado = calibrar_batch(fichas, {}, client=client)
    por_ra = {f.ra: f.nota_a1 for f in resultado}

    # Ambos os empatados mantêm nota >9.0 (estão no top por empate)
    assert por_ra[_ra(1)] == pytest.approx(9.7)
    assert por_ra[_ra(2)] == pytest.approx(9.7)
    # O terceiro, fora do top, sofre cap
    assert por_ra[_ra(3)] == pytest.approx(9.0)


# ---------------------------------------------------------------------------
# TC-CAL-04 — batch de 1 aluno (top_n = ceil(0.10 × 1) = 1)
# ---------------------------------------------------------------------------


def test_tc_cal_04_batch_de_um_aluno():
    """Único aluno é 100% do batch → está no top, cap 9 NÃO se aplica."""
    fichas = [_ficha(1, 8.0)]
    client = _mock_client(_mock_response_ranking(fichas))

    resultado = calibrar_batch(fichas, {}, client=client)

    assert len(resultado) == 1
    # Nota preservada mesmo sendo <=9 (cap não se aplica a quem está no top)
    assert resultado[0].nota_a1 == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# TC-CAL-05 — batch de 10 alunos com nota máxima 7.5 (cap nunca ativa)
# ---------------------------------------------------------------------------


def test_tc_cal_05_batch_10_alunos_estrutural():
    """N=10, todas as notas <=7.5: top_n=1, len=10, cap nunca dispara."""
    fichas = [
        _ficha(1, 7.5),  # top (única)
        _ficha(2, 7.0),
        _ficha(3, 6.5),
        _ficha(4, 6.0),
        _ficha(5, 5.5),
        _ficha(6, 5.0),
        _ficha(7, 4.5),
        _ficha(8, 4.0),
        _ficha(9, 3.5),
        _ficha(10, 3.0),
    ]
    client = _mock_client(_mock_response_ranking(fichas))

    resultado = calibrar_batch(fichas, {}, client=client)

    assert len(resultado) == 10
    # Nenhuma nota excede 9.0 (cap não ativa, mas verificamos preservação)
    for original, calibrada in zip(fichas, resultado, strict=True):
        assert calibrada.nota_a1 == pytest.approx(original.nota_a1)
        # Sanity: nenhuma nota acima de 9.0
        assert calibrada.nota_a1 is not None
        assert calibrada.nota_a1 <= 9.0


# ---------------------------------------------------------------------------
# TC-CAL-06 — mock do Sonnet valida parâmetros de chamada
# ---------------------------------------------------------------------------


def test_tc_cal_06_mock_valida_parametros_de_chamada():
    """Verifica model, temperature, max_tokens, cache_control e PII ausente."""
    fichas = [_ficha(i, 7.0 + i / 10) for i in range(1, 6)]  # 5 alunos
    client = _mock_client(_mock_response_ranking(fichas))

    calibrar_batch(fichas, {"turma": "T1"}, client=client)

    # Chamado exatamente 1 vez
    assert client.messages.create.call_count == 1

    kwargs = client.messages.create.call_args.kwargs

    # AC-02 — modelo Sonnet 4.6
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["model"] == MODELO_CALIBRACAO

    # ADR-003 — temperature determinística
    assert kwargs["temperature"] == 0
    assert kwargs["temperature"] == TEMPERATURE_CALIBRACAO

    # AC-03 — max_tokens=4096
    assert kwargs["max_tokens"] == 4096
    assert kwargs["max_tokens"] == MAX_TOKENS_CALIBRACAO

    # AC-07 — timeout explícito (V6 ADR-002)
    assert kwargs["timeout"] == 90
    assert kwargs["timeout"] == API_TIMEOUT

    # AC-06 — system prompt com cache_control ephemeral (V9 ADR-002)
    system = kwargs["system"]
    assert isinstance(system, list)
    assert len(system) == 1
    assert system[0]["type"] == "text"
    assert system[0]["cache_control"] == {"type": "ephemeral"}

    # AC-08 — payload sem PII (sem nomes; só RA + nota)
    messages = kwargs["messages"]
    assert len(messages) == 1
    user_content = messages[0]["content"]
    # Não deve conter palavras-chave típicas de PII de aluno
    assert "nome" not in user_content.lower()
    assert "feedback" not in user_content.lower()
    # Deve conter os RAs (esperado — eles SÃO o identificador permitido por ADR-004)
    for f in fichas:
        assert f.ra in user_content


# ---------------------------------------------------------------------------
# TC-CAL-07 (bônus) — batch vazio NÃO chama API (guard)
# ---------------------------------------------------------------------------


def test_tc_cal_07_batch_vazio_retorna_lista_vazia_sem_chamar_api():
    """``if not fichas: return []`` — guard explícito da story (Risco 3)."""
    client = _mock_client(_mock_response_ranking([]))

    resultado = calibrar_batch([], {}, client=client)

    assert resultado == []
    assert client.messages.create.call_count == 0


# ---------------------------------------------------------------------------
# TC-CAL-08 (bônus) — resposta malformada do Sonnet aplica apenas cap 9
# ---------------------------------------------------------------------------


def test_tc_cal_08_resposta_malformada_aplica_apenas_cap_9():
    """Se o Sonnet devolver lixo, calibrador aplica cap 9 sobre notas brutas."""
    fichas = [
        _ficha(1, 9.9),  # top
        _ficha(2, 9.5),  # cap → 9.0
        _ficha(3, 9.2),  # cap → 9.0
        *[_ficha(i, 7.0) for i in range(4, 11)],
    ]
    resposta_lixo = SimpleNamespace(content=[SimpleNamespace(text="não é json válido {{{")])
    client = _mock_client(resposta_lixo)

    resultado = calibrar_batch(fichas, {}, client=client)
    por_ra = {f.ra: f.nota_a1 for f in resultado}

    # Top preservado (sem ajuste, mantém nota bruta)
    assert por_ra[_ra(1)] == pytest.approx(9.9)
    # Fora do top com >9.0 sofrem cap mesmo sem ajuste do Sonnet
    assert por_ra[_ra(2)] == pytest.approx(9.0)
    assert por_ra[_ra(3)] == pytest.approx(9.0)


# ---------------------------------------------------------------------------
# TC-CAL-09 (bônus) — log_action chamado com payload sem PII (AC-10)
# ---------------------------------------------------------------------------


def test_tc_cal_09_log_action_sem_pii(monkeypatch):
    """``log_action`` recebe descrição agregada, nunca RA/nome individual."""
    fichas = [_ficha(i, 7.0) for i in range(1, 11)]
    client = _mock_client(_mock_response_ranking(fichas))

    fake_log = MagicMock()
    monkeypatch.setattr(cal, "log_action", fake_log)

    calibrar_batch(fichas, {}, client=client)

    # log_action chamado ao menos uma vez (início_calibracao)
    assert fake_log.call_count >= 1
    kwargs = fake_log.call_args_list[0].kwargs
    assert kwargs["acao"] == "inicio_calibracao"
    payload = kwargs["payload_resumido"]
    # Sem RAs individuais no payload (ADR-004)
    import re

    assert not re.search(r"\b\d{11}\b", payload), f"RA em payload: {payload!r}"
    # Deve conter agregado N alunos
    assert "10 alunos" in payload
    assert "Sonnet" in payload
