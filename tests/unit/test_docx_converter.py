"""Testes unitários para docx_converter — Story 1.7."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.converters.docx_converter import convert_docx

FIXTURE_DOCX = Path("docs/fixtures/batch-exemplo/aluno-c-relatorio.docx")


class TestConvertDocxOutputStructure:
    """Estrutura do dict retornado — AC5."""

    def test_retorna_dict_com_campos_obrigatorios(self, tmp_path: Path) -> None:
        docx_fake = tmp_path / "qualquer.docx"
        docx_fake.write_bytes(b"nao e docx valido")
        resultado = convert_docx(docx_fake)
        assert isinstance(resultado, dict)
        assert "texto" in resultado
        assert "paragrafos" in resultado
        assert "metodo_extracao" in resultado
        assert "flags" in resultado

    def test_texto_e_string(self, tmp_path: Path) -> None:
        docx_fake = tmp_path / "qualquer.docx"
        docx_fake.write_bytes(b"corrompido")
        resultado = convert_docx(docx_fake)
        assert isinstance(resultado["texto"], str)

    def test_paragrafos_e_int(self, tmp_path: Path) -> None:
        docx_fake = tmp_path / "qualquer.docx"
        docx_fake.write_bytes(b"corrompido")
        resultado = convert_docx(docx_fake)
        assert isinstance(resultado["paragrafos"], int)

    def test_flags_e_lista(self, tmp_path: Path) -> None:
        docx_fake = tmp_path / "qualquer.docx"
        docx_fake.write_bytes(b"corrompido")
        resultado = convert_docx(docx_fake)
        assert isinstance(resultado["flags"], list)

    def test_metodo_extracao_valido(self, tmp_path: Path) -> None:
        docx_fake = tmp_path / "qualquer.docx"
        docx_fake.write_bytes(b"corrompido")
        resultado = convert_docx(docx_fake)
        assert resultado["metodo_extracao"] in {"nativo", "nenhum"}


class TestConvertDocxFixture:
    """AC1 — fixture aluno-c-relatorio.docx converte com >100 chars."""

    def test_fixture_converte_com_mais_de_100_chars(self) -> None:
        assert FIXTURE_DOCX.exists(), f"Fixture esperada em {FIXTURE_DOCX} (gerada na Story 0.1)"

        resultado = convert_docx(FIXTURE_DOCX)

        assert resultado["flags"] == []
        assert resultado["metodo_extracao"] == "nativo"
        assert isinstance(resultado["texto"], str)
        assert len(resultado["texto"]) > 100
        assert isinstance(resultado["paragrafos"], int)
        assert resultado["paragrafos"] > 0


class TestConvertDocxFormatoLegado:
    """AC2 — arquivo .doc legado retorna flag formato_nao_suportado."""

    def test_doc_legado_retorna_formato_nao_suportado(self, tmp_path: Path) -> None:
        doc_legado = tmp_path / "relatorio.doc"
        doc_legado.write_bytes(b"\xd0\xcf\x11\xe0 formato binario legado")  # magic OLE
        resultado = convert_docx(doc_legado)
        assert "formato_nao_suportado" in resultado["flags"]
        assert resultado["texto"] == ""
        assert resultado["paragrafos"] == 0
        assert resultado["metodo_extracao"] == "nenhum"

    def test_doc_legado_extensao_maiuscula(self, tmp_path: Path) -> None:
        # Resiliência: extensões em caixa alta devem ser detectadas
        doc_legado = tmp_path / "RELATORIO.DOC"
        doc_legado.write_bytes(b"legado")
        resultado = convert_docx(doc_legado)
        assert "formato_nao_suportado" in resultado["flags"]

    def test_docx_nao_e_detectado_como_doc_legado(self, tmp_path: Path) -> None:
        # Garantir que .docx não dispara a flag formato_nao_suportado
        docx_fake = tmp_path / "arquivo.docx"
        docx_fake.write_bytes(b"corrompido mas com extensao docx")
        resultado = convert_docx(docx_fake)
        assert "formato_nao_suportado" not in resultado["flags"]


class TestConvertDocxTamanho:
    """AC3 — DOCX > 10MB é rejeitado com mensagem clara antes de processar."""

    def test_arquivo_muito_grande_lanca_value_error(self, tmp_path: Path) -> None:
        docx_grande = tmp_path / "grande.docx"
        docx_grande.write_bytes(b"PK fake docx")

        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 11 * 1024 * 1024  # 11 MB
            with pytest.raises(ValueError, match="Arquivo muito grande"):
                convert_docx(docx_grande)

    def test_mensagem_de_erro_inclui_tamanho_e_limite(self, tmp_path: Path) -> None:
        docx_grande = tmp_path / "grande.docx"
        docx_grande.write_bytes(b"PK fake docx")

        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 25 * 1024 * 1024  # 25 MB
            with pytest.raises(ValueError, match=r"25MB.*10MB"):
                convert_docx(docx_grande)


class TestConvertDocxCorrompido:
    """AC4 — DOCX corrompido retorna flag arquivo_ilegivel sem propagar exceção."""

    def test_arquivo_corrompido_retorna_arquivo_ilegivel(self, tmp_path: Path) -> None:
        corrompido = tmp_path / "corrompido.docx"
        corrompido.write_bytes(b"nao e docx valido")
        resultado = convert_docx(corrompido)
        assert "arquivo_ilegivel" in resultado["flags"]
        assert resultado["texto"] == ""
        assert resultado["paragrafos"] == 0
        assert resultado["metodo_extracao"] == "nenhum"

    def test_arquivo_inexistente_retorna_ilegivel(self, tmp_path: Path) -> None:
        inexistente = tmp_path / "nao_existe.docx"
        resultado = convert_docx(inexistente)
        assert "arquivo_ilegivel" in resultado["flags"]

    def test_arquivo_vazio_retorna_ilegivel(self, tmp_path: Path) -> None:
        vazio = tmp_path / "vazio.docx"
        vazio.write_bytes(b"")
        resultado = convert_docx(vazio)
        assert "arquivo_ilegivel" in resultado["flags"]

    def test_nao_propaga_excecao_para_qualquer_lixo_binario(self, tmp_path: Path) -> None:
        # Garantia AC4: nenhuma exceção propaga
        lixo = tmp_path / "lixo.docx"
        lixo.write_bytes(b"\x00\x01\x02\x03 random bytes \xff\xfe")
        resultado = convert_docx(lixo)
        assert "arquivo_ilegivel" in resultado["flags"]
