"""Testes unitários para image_converter — Story 1.8."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from src.converters.image_converter import (
    FORMATOS_SUPORTADOS,
    MAX_FILE_BYTES,
    convert_image,
)


def _criar_png_sintetico(path: Path, texto: str = "exemplo de texto") -> None:
    """Cria um PNG sintético com texto legível usando Pillow ImageDraw."""
    img = Image.new("RGB", (400, 120), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 40), texto, fill="black")
    img.save(path, format="PNG")
    img.close()


class TestConvertImageOutputStructure:
    def test_retorna_dict_com_campos_obrigatorios(self, tmp_path: Path) -> None:
        img_path = tmp_path / "exemplo.png"
        _criar_png_sintetico(img_path)
        with patch(
            "src.converters.image_converter.pytesseract.image_to_string",
            return_value="texto sintético",
        ):
            resultado = convert_image(img_path)
        assert isinstance(resultado, dict)
        assert "texto" in resultado
        assert "paginas" in resultado
        assert "metodo_extracao" in resultado
        assert "flags" in resultado

    def test_paginas_sempre_um(self, tmp_path: Path) -> None:
        img_path = tmp_path / "exemplo.png"
        _criar_png_sintetico(img_path)
        with patch(
            "src.converters.image_converter.pytesseract.image_to_string",
            return_value="conteudo qualquer",
        ):
            resultado = convert_image(img_path)
        assert resultado["paginas"] == 1

    def test_texto_e_string(self, tmp_path: Path) -> None:
        img_path = tmp_path / "qualquer.png"
        _criar_png_sintetico(img_path)
        with patch(
            "src.converters.image_converter.pytesseract.image_to_string",
            return_value="ok",
        ):
            resultado = convert_image(img_path)
        assert isinstance(resultado["texto"], str)

    def test_flags_e_lista(self, tmp_path: Path) -> None:
        gif_fake = tmp_path / "anim.gif"
        gif_fake.write_bytes(b"GIF89a fake")
        resultado = convert_image(gif_fake)
        assert isinstance(resultado["flags"], list)


class TestFormatosSuportados:
    def test_jpg_aceito(self, tmp_path: Path) -> None:
        img_path = tmp_path / "foto.jpg"
        img = Image.new("RGB", (100, 50), color="white")
        img.save(img_path, format="JPEG")
        img.close()
        with patch(
            "src.converters.image_converter.pytesseract.image_to_string",
            return_value="texto jpg",
        ):
            resultado = convert_image(img_path)
        assert resultado["metodo_extracao"] == "ocr"
        assert resultado["texto"] == "texto jpg"
        assert resultado["flags"] == []

    def test_jpeg_aceito(self, tmp_path: Path) -> None:
        img_path = tmp_path / "foto.jpeg"
        img = Image.new("RGB", (100, 50), color="white")
        img.save(img_path, format="JPEG")
        img.close()
        with patch(
            "src.converters.image_converter.pytesseract.image_to_string",
            return_value="abc",
        ):
            resultado = convert_image(img_path)
        assert resultado["metodo_extracao"] == "ocr"

    def test_png_aceito(self, tmp_path: Path) -> None:
        img_path = tmp_path / "captura.png"
        _criar_png_sintetico(img_path)
        with patch(
            "src.converters.image_converter.pytesseract.image_to_string",
            return_value="conteudo png",
        ):
            resultado = convert_image(img_path)
        assert resultado["metodo_extracao"] == "ocr"
        assert resultado["texto"] == "conteudo png"

    def test_webp_aceito(self, tmp_path: Path) -> None:
        img_path = tmp_path / "imagem.webp"
        img = Image.new("RGB", (100, 50), color="white")
        img.save(img_path, format="WEBP")
        img.close()
        with patch(
            "src.converters.image_converter.pytesseract.image_to_string",
            return_value="texto webp",
        ):
            resultado = convert_image(img_path)
        assert resultado["metodo_extracao"] == "ocr"

    def test_extensao_maiuscula_aceita(self, tmp_path: Path) -> None:
        img_path = tmp_path / "FOTO.PNG"
        _criar_png_sintetico(img_path)
        with patch(
            "src.converters.image_converter.pytesseract.image_to_string",
            return_value="ok",
        ):
            resultado = convert_image(img_path)
        assert resultado["metodo_extracao"] == "ocr"


class TestFormatoNaoSuportado:
    def test_gif_retorna_formato_nao_suportado(self, tmp_path: Path) -> None:
        gif_fake = tmp_path / "anim.gif"
        gif_fake.write_bytes(b"GIF89a fake")
        resultado = convert_image(gif_fake)
        assert "formato_nao_suportado" in resultado["flags"]
        assert resultado["texto"] == ""
        assert resultado["metodo_extracao"] == "nenhum"
        assert resultado["paginas"] == 1

    def test_bmp_retorna_formato_nao_suportado(self, tmp_path: Path) -> None:
        bmp_fake = tmp_path / "mapa.bmp"
        bmp_fake.write_bytes(b"BM fake")
        resultado = convert_image(bmp_fake)
        assert "formato_nao_suportado" in resultado["flags"]

    def test_tiff_retorna_formato_nao_suportado(self, tmp_path: Path) -> None:
        tiff_fake = tmp_path / "scan.tiff"
        tiff_fake.write_bytes(b"II*\x00 fake")
        resultado = convert_image(tiff_fake)
        assert "formato_nao_suportado" in resultado["flags"]

    def test_sem_extensao_retorna_formato_nao_suportado(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "sem_extensao"
        arquivo.write_bytes(b"qualquer coisa")
        resultado = convert_image(arquivo)
        assert "formato_nao_suportado" in resultado["flags"]


class TestLimiteDeTamanho:
    def test_arquivo_muito_grande_lanca_value_error(self, tmp_path: Path) -> None:
        img_path = tmp_path / "grande.png"
        img_path.write_bytes(b"PNG fake")

        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 6 * 1024 * 1024  # 6 MB > 5 MB
            with pytest.raises(ValueError, match="Arquivo muito grande"):
                convert_image(img_path)

    def test_arquivo_no_limite_5mb_aceito(self, tmp_path: Path) -> None:
        img_path = tmp_path / "limite.png"
        _criar_png_sintetico(img_path)

        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = MAX_FILE_BYTES  # exatamente 5 MB
            with patch(
                "src.converters.image_converter.pytesseract.image_to_string",
                return_value="ok",
            ):
                resultado = convert_image(img_path)
        assert resultado["metodo_extracao"] == "ocr"

    def test_mensagem_de_erro_menciona_limite_5mb(self, tmp_path: Path) -> None:
        img_path = tmp_path / "grande.jpg"
        img_path.write_bytes(b"JPG fake")

        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 10 * 1024 * 1024
            with pytest.raises(ValueError, match="5MB"):
                convert_image(img_path)


class TestArquivoIlegivel:
    def test_arquivo_inexistente_retorna_ilegivel(self, tmp_path: Path) -> None:
        inexistente = tmp_path / "nao_existe.png"
        resultado = convert_image(inexistente)
        assert "arquivo_ilegivel" in resultado["flags"]
        assert resultado["texto"] == ""
        assert resultado["metodo_extracao"] == "nenhum"

    def test_png_corrompido_retorna_ilegivel(self, tmp_path: Path) -> None:
        corrompido = tmp_path / "corrompido.png"
        corrompido.write_bytes(b"isso nao e um PNG valido")
        resultado = convert_image(corrompido)
        assert "arquivo_ilegivel" in resultado["flags"]
        assert resultado["texto"] == ""


class TestOcrSucesso:
    def test_ocr_extrai_texto_nao_vazio(self, tmp_path: Path) -> None:
        img_path = tmp_path / "trabalho.png"
        _criar_png_sintetico(img_path, "Resposta do aluno em portugues")
        with patch(
            "src.converters.image_converter.pytesseract.image_to_string",
            return_value="Resposta do aluno em portugues",
        ):
            resultado = convert_image(img_path)
        assert resultado["texto"] != ""
        assert resultado["metodo_extracao"] == "ocr"
        assert resultado["flags"] == []

    def test_ocr_usa_lingua_portugues(self, tmp_path: Path) -> None:
        img_path = tmp_path / "trabalho.png"
        _criar_png_sintetico(img_path)
        with patch(
            "src.converters.image_converter.pytesseract.image_to_string",
            return_value="texto",
        ) as mock_ocr:
            convert_image(img_path)
        assert mock_ocr.called
        _, kwargs = mock_ocr.call_args
        assert kwargs.get("lang") == "por"

    def test_ocr_retornando_apenas_whitespace_marca_extracao_falhou(self, tmp_path: Path) -> None:
        img_path = tmp_path / "branco.png"
        _criar_png_sintetico(img_path)
        with patch(
            "src.converters.image_converter.pytesseract.image_to_string",
            return_value="   \n  \n",
        ):
            resultado = convert_image(img_path)
        assert resultado["texto"] == ""
        assert resultado["metodo_extracao"] == "nenhum"
        assert "extracao_falhou" in resultado["flags"]

    def test_ocr_remove_caracteres_de_controle(self, tmp_path: Path) -> None:
        img_path = tmp_path / "trabalho.png"
        _criar_png_sintetico(img_path)
        with patch(
            "src.converters.image_converter.pytesseract.image_to_string",
            return_value="texto\x00com\x01controle",
        ):
            resultado = convert_image(img_path)
        assert "\x00" not in str(resultado["texto"])
        assert "\x01" not in str(resultado["texto"])


class TestConstantes:
    def test_formatos_suportados_contem_quatro_extensoes(self) -> None:
        assert {".jpg", ".jpeg", ".png", ".webp"} == FORMATOS_SUPORTADOS

    def test_max_file_bytes_e_5mb(self) -> None:
        assert MAX_FILE_BYTES == 5 * 1024 * 1024
