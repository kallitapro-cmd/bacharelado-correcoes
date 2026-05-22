"""Testes unitários para pdf_converter — Story 1.5."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.converters.pdf_converter import convert_pdf


class TestConvertPdfOutputStructure:
    def test_retorna_dict_com_campos_obrigatorios(self, tmp_path):
        pdf_fake = tmp_path / "vazio.pdf"
        pdf_fake.write_bytes(b"%PDF-1.4 fake")
        resultado = convert_pdf(pdf_fake)
        assert isinstance(resultado, dict)
        assert "texto" in resultado
        assert "paginas" in resultado
        assert "metodo_extracao" in resultado
        assert "flags" in resultado

    def test_arquivo_ilegivel_quando_corrompido(self, tmp_path):
        corrompido = tmp_path / "corrompido.pdf"
        corrompido.write_bytes(b"nao e um pdf valido")
        resultado = convert_pdf(corrompido)
        assert "arquivo_ilegivel" in resultado["flags"]
        assert resultado["texto"] == ""
        assert resultado["metodo_extracao"] == "nenhum"

    def test_arquivo_ilegivel_quando_nao_existe(self, tmp_path):
        inexistente = tmp_path / "nao_existe.pdf"
        resultado = convert_pdf(inexistente)
        assert "arquivo_ilegivel" in resultado["flags"]

    def test_arquivo_muito_grande_lanca_value_error(self, tmp_path, monkeypatch):
        pdf_grande = tmp_path / "grande.pdf"
        pdf_grande.write_bytes(b"%PDF-1.4")

        import os

        monkeypatch.setattr(os.path, "getsize", lambda _: 11 * 1024 * 1024)

        from unittest.mock import patch

        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 11 * 1024 * 1024
            with pytest.raises(ValueError, match="Arquivo muito grande"):
                convert_pdf(pdf_grande)

    def test_metodo_extracao_valido(self, tmp_path):
        pdf_fake = tmp_path / "qualquer.pdf"
        pdf_fake.write_bytes(b"%PDF-1.4 fake")
        resultado = convert_pdf(pdf_fake)
        assert resultado["metodo_extracao"] in {"nativo", "ocr", "nenhum"}

    def test_flags_e_lista(self, tmp_path):
        pdf_fake = tmp_path / "qualquer.pdf"
        pdf_fake.write_bytes(b"nao e pdf")
        resultado = convert_pdf(pdf_fake)
        assert isinstance(resultado["flags"], list)

    def test_texto_e_string(self, tmp_path):
        pdf_fake = tmp_path / "qualquer.pdf"
        pdf_fake.write_bytes(b"nao e pdf")
        resultado = convert_pdf(pdf_fake)
        assert isinstance(resultado["texto"], str)
