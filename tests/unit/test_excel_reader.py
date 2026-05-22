"""Testes unitários para read_aba1() — Story 1.10."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.excel.excel_reader import read_aba1
from src.models.schemas import Aluno

FIXTURES_DIR = Path(__file__).parent.parent.parent / "docs" / "fixtures"
PLANILHA = FIXTURES_DIR / "aba1-exemplo-anon.xlsx"


class TestReadAba1:
    """Cobre os 3 padrões de RA da fixture + garantias de imutabilidade."""

    def test_retorna_8_alunos(self) -> None:
        alunos = read_aba1(PLANILHA)
        assert len(alunos) == 8

    def test_todos_os_itens_são_instâncias_aluno(self) -> None:
        alunos = read_aba1(PLANILHA)
        assert all(isinstance(a, Aluno) for a in alunos)

    def test_ras_11_digitos_canónicos_preservados(self) -> None:
        alunos = read_aba1(PLANILHA)
        ras = {a.ra for a in alunos}
        assert "20260100418" in ras
        assert "20260100419" in ras
        assert "20260100501" in ras
        assert "20250100621" in ras
        assert "20260100777" in ras

    def test_ras_10_digitos_normalizados_para_11(self) -> None:
        alunos = read_aba1(PLANILHA)
        ras = {a.ra for a in alunos}
        # RAs legados da fixture: 2026100420 e 2025100333
        assert "20261004200" not in ras, "zfill inválido não deve aparecer"
        assert "20260100420" in ras, "RA legado 2026 deve ser normalizado"
        assert "20250100333" in ras, "RA legado 2025 deve ser normalizado"

    def test_ra_especial_0000_preservado_camada3(self) -> None:
        alunos = read_aba1(PLANILHA)
        ras = {a.ra for a in alunos}
        assert "0000100041" in ras

    def test_nomes_preenchidos(self) -> None:
        alunos = read_aba1(PLANILHA)
        assert all(a.nome for a in alunos)

    def test_emails_preenchidos(self) -> None:
        alunos = read_aba1(PLANILHA)
        assert all(a.email for a in alunos)

    def test_planilha_não_é_modificada(self, tmp_path: Path) -> None:
        import shutil

        copia = tmp_path / "aba1-copia.xlsx"
        shutil.copy2(PLANILHA, copia)
        tamanho_antes = copia.stat().st_size
        mtime_antes = copia.stat().st_mtime

        read_aba1(copia)

        assert copia.stat().st_size == tamanho_antes
        assert copia.stat().st_mtime == mtime_antes

    def test_coluna_ra_ausente_levanta_value_error(self, tmp_path: Path) -> None:
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Nome Completo", "E-mail"])
        ws.append(["Aluno Teste", "x@y.com"])
        caminho = tmp_path / "sem-ra.xlsx"
        wb.save(caminho)

        with pytest.raises(ValueError, match="Coluna RA não encontrada"):
            read_aba1(caminho)

    def test_colunas_em_ordem_diferente(self, tmp_path: Path) -> None:
        """Fixture com colunas reordenadas ainda deve funcionar."""
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Telefone", "E-mail", "Nome Completo", "RA"])
        ws.append(["(11) 99999-0001", "x@y.com", "Aluno Teste", "20260100418"])
        caminho = tmp_path / "reordenado.xlsx"
        wb.save(caminho)

        alunos = read_aba1(caminho)
        assert len(alunos) == 1
        assert alunos[0].ra == "20260100418"
        assert alunos[0].nome == "Aluno Teste"
