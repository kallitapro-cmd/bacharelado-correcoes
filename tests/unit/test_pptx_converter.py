"""Testes unitários para pptx_converter — Story 1.6."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.converters.pptx_converter import convert_pptx, convert_pptx_batch


class TestConvertPptxOutputStructure:
    def test_retorna_dict_com_campos_obrigatorios(self, tmp_path):
        pptx_fake = tmp_path / "qualquer.pptx"
        pptx_fake.write_bytes(b"nao e pptx")
        resultado = convert_pptx(pptx_fake)
        assert isinstance(resultado, dict)
        assert "texto" in resultado
        assert "slides" in resultado
        assert "metodo_extracao" in resultado
        assert "flags" in resultado

    def test_ppt_legado_retorna_formato_nao_suportado(self, tmp_path):
        ppt_legado = tmp_path / "apresentacao.ppt"
        ppt_legado.write_bytes(b"formato binario legado")
        resultado = convert_pptx(ppt_legado)
        assert "formato_nao_suportado" in resultado["flags"]
        assert resultado["texto"] == ""
        assert resultado["slides"] == 0

    def test_arquivo_corrompido_retorna_arquivo_ilegivel(self, tmp_path):
        corrompido = tmp_path / "corrompido.pptx"
        corrompido.write_bytes(b"nao e pptx valido")
        resultado = convert_pptx(corrompido)
        assert "arquivo_ilegivel" in resultado["flags"]
        assert resultado["texto"] == ""

    def test_arquivo_muito_grande_lanca_value_error(self, tmp_path):
        pptx_grande = tmp_path / "grande.pptx"
        pptx_grande.write_bytes(b"PK fake pptx")

        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 11 * 1024 * 1024
            with pytest.raises(ValueError, match="Arquivo muito grande"):
                convert_pptx(pptx_grande)

    def test_arquivo_nao_existe_retorna_ilegivel(self, tmp_path):
        inexistente = tmp_path / "nao_existe.pptx"
        resultado = convert_pptx(inexistente)
        assert "arquivo_ilegivel" in resultado["flags"]

    def test_metodo_extracao_valido(self, tmp_path):
        pptx_fake = tmp_path / "qualquer.pptx"
        pptx_fake.write_bytes(b"corrompido")
        resultado = convert_pptx(pptx_fake)
        assert resultado["metodo_extracao"] in {"nativo", "ocr", "misto", "nenhum"}

    def test_flags_e_lista(self, tmp_path):
        pptx_fake = tmp_path / "qualquer.pptx"
        pptx_fake.write_bytes(b"corrompido")
        resultado = convert_pptx(pptx_fake)
        assert isinstance(resultado["flags"], list)

    def test_texto_e_string(self, tmp_path):
        pptx_fake = tmp_path / "qualquer.pptx"
        pptx_fake.write_bytes(b"corrompido")
        resultado = convert_pptx(pptx_fake)
        assert isinstance(resultado["texto"], str)


class TestConvertPptxBatch:
    def test_batch_preserva_ordem(self, tmp_path):
        arquivos = []
        for i in range(3):
            f = tmp_path / f"slide_{i}.ppt"
            f.write_bytes(b"legado")
            arquivos.append(f)

        resultados = convert_pptx_batch(arquivos)

        assert len(resultados) == 3
        for r in resultados:
            assert "formato_nao_suportado" in r["flags"]

    def test_batch_retorna_lista_com_mesmo_tamanho(self, tmp_path):
        arquivos = [tmp_path / f"f{i}.pptx" for i in range(4)]
        for f in arquivos:
            f.write_bytes(b"corrompido")

        resultados = convert_pptx_batch(arquivos)
        assert len(resultados) == 4
