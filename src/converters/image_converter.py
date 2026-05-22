"""Conversor de imagens -> texto. Story 1.8 — Pillow + pytesseract OCR."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytesseract
from PIL import Image, UnidentifiedImageError

FORMATOS_SUPORTADOS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB


def convert_image(file_path: str | Path) -> dict[str, object]:
    """Converte uma imagem em texto via OCR.

    Args:
        file_path: caminho do arquivo de imagem.

    Returns:
        dict com campos:
        - texto (str): texto extraído via OCR ou string vazia se falhou
        - paginas (int): sempre 1 para imagens individuais
        - metodo_extracao (str): "ocr" em caso de sucesso; "nenhum" caso contrário
        - flags (list[str]): vazio = sucesso; possíveis valores:
            "formato_nao_suportado", "arquivo_ilegivel", "extracao_falhou"

    Raises:
        ValueError: quando o arquivo excede MAX_FILE_BYTES (5 MB).
    """
    file_path = Path(file_path)

    extensao = file_path.suffix.lower()
    if extensao not in FORMATOS_SUPORTADOS:
        return _falha("formato_nao_suportado")

    try:
        tamanho = file_path.stat().st_size
    except OSError:
        return _falha("arquivo_ilegivel")

    if tamanho > MAX_FILE_BYTES:
        mb = tamanho // (1024 * 1024)
        raise ValueError(f"Arquivo muito grande: {mb}MB. Limite: 5MB.")

    try:
        # M3 — fechar Pillow Image após uso
        img = Image.open(file_path).convert("RGB")
        try:
            texto = pytesseract.image_to_string(img, lang="por")
        finally:
            img.close()
    except (UnidentifiedImageError, OSError):
        return _falha("arquivo_ilegivel")
    except Exception:
        # ADR-004 — não logar conteúdo do trabalho do aluno
        return _falha("extracao_falhou")

    texto_sanitizado = _sanitizar(texto)
    if not texto_sanitizado:
        return {
            "texto": "",
            "paginas": 1,
            "metodo_extracao": "nenhum",
            "flags": ["extracao_falhou"],
        }

    return {
        "texto": texto_sanitizado,
        "paginas": 1,
        "metodo_extracao": "ocr",
        "flags": [],
    }


def _sanitizar(texto: str) -> str:
    """Remove caracteres de controle e normaliza encoding UTF-8."""
    texto = unicodedata.normalize("NFC", texto)
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", texto)
    return texto.strip()


def _falha(flag: str) -> dict[str, object]:
    return {
        "texto": "",
        "paginas": 1,
        "metodo_extracao": "nenhum",
        "flags": [flag],
    }
