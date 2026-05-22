"""Conversor PDF -> texto. Story 1.5 — PyMuPDF + fallback OCR pytesseract."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
MIN_CHARS_NATIVE = 100  # threshold para decidir se OCR é necessário
MAX_PAGES_OCR = 20  # R2 — além disso, retorna flag "ocr_parcial"
OCR_EARLY_EXIT_CHARS = 200  # R1 — acumular este mínimo e parar OCR


def convert_pdf(file_path: str | Path) -> dict[str, object]:
    """Converte um arquivo PDF em texto.

    Returns:
        dict com campos:
        - texto (str): texto extraído ou string vazia se falhou
        - paginas (int): número de páginas
        - metodo_extracao (str): "nativo", "ocr" ou "nenhum"
        - flags (list[str]): vazio = sucesso; possíveis valores:
            "arquivo_muito_grande", "arquivo_ilegivel",
            "extracao_falhou", "ocr_parcial"
    """
    file_path = Path(file_path)
    flags: list[str] = []

    # Sanitização de input: rejeitar extensões não-PDF antes de abrir com fitz.
    # fitz.open() aceita qualquer bytes — sem esta guarda, um .exe renomeado
    # para .pdf seria processado e poderia acionar parsers C vulneráveis do MuPDF.
    if file_path.suffix.lower() != ".pdf":
        return _falha("arquivo_ilegivel", paginas=0)

    # Checar tamanho antes de abrir
    try:
        tamanho = file_path.stat().st_size
    except OSError:
        return _falha("arquivo_ilegivel", paginas=0)

    if tamanho > MAX_FILE_BYTES:
        mb = tamanho // (1024 * 1024)
        raise ValueError(f"Arquivo muito grande: {mb}MB. Limite: 10MB.")

    doc: fitz.Document | None = None
    try:
        # M1 — context manager garante close() mesmo em exceção.
        # A variável `doc` é atribuída antes do with para que o finally
        # possa chamar doc.close() como dupla proteção anti-OOM no Streamlit Cloud.
        with fitz.open(str(file_path)) as doc:
            # M4 — PDFs protegidos por senha retornam texto vazio sem erro;
            # detectar antes para classificar corretamente como ilegível
            if doc.needs_pass:
                return _falha("arquivo_ilegivel", paginas=len(doc))

            paginas = len(doc)

            # R1 — early exit: parar quando threshold atingido, sem carregar tudo
            texto_nativo, chars_acumulados = _extrair_nativo(doc)

            if chars_acumulados >= MIN_CHARS_NATIVE:
                return {
                    "texto": _sanitizar(texto_nativo),
                    "paginas": paginas,
                    "metodo_extracao": "nativo",
                    "flags": [],
                }

            # Fallback OCR
            texto_ocr, ocr_parcial = _extrair_ocr(doc, paginas)
            if ocr_parcial:
                flags.append("ocr_parcial")  # R2

            if texto_ocr.strip():
                return {
                    "texto": _sanitizar(texto_ocr),
                    "paginas": paginas,
                    "metodo_extracao": "ocr",
                    "flags": flags,
                }

            flags.append("extracao_falhou")
            return {
                "texto": "",
                "paginas": paginas,
                "metodo_extracao": "nenhum",
                "flags": flags,
            }

    except fitz.FileDataError:
        return _falha("arquivo_ilegivel", paginas=0)
    except Exception:
        return _falha("arquivo_ilegivel", paginas=0)
    finally:
        # Dupla proteção anti-OOM: garante close() mesmo se o context manager
        # falhar silenciosamente em edge cases do Streamlit Cloud (1 GB RAM limit).
        if doc is not None and not doc.is_closed:
            doc.close()


def _extrair_nativo(doc: fitz.Document) -> tuple[str, int]:
    """Extrai texto nativo com early exit assim que MIN_CHARS_NATIVE for atingido."""
    partes: list[str] = []
    chars_total = 0
    for page in doc:
        texto_pagina = page.get_text()
        partes.append(texto_pagina)
        chars_total += len(texto_pagina.strip())
        if chars_total >= MIN_CHARS_NATIVE:
            break
    return "\n".join(partes), chars_total


def _extrair_ocr(doc: fitz.Document, total_paginas: int) -> tuple[str, bool]:
    """OCR página a página com limite MAX_PAGES_OCR e early exit por acúmulo."""
    ocr_parcial = total_paginas > MAX_PAGES_OCR
    paginas_a_processar = min(total_paginas, MAX_PAGES_OCR)
    partes: list[str] = []
    chars_acumulados = 0

    for i, page in enumerate(doc):
        if i >= paginas_a_processar:
            break
        pixmap = page.get_pixmap(dpi=150)
        img = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        try:
            texto_pagina = pytesseract.image_to_string(img, lang="por")
            partes.append(texto_pagina)
            chars_acumulados += len(texto_pagina.strip())
        finally:
            img.close()
            del pixmap

        if chars_acumulados >= OCR_EARLY_EXIT_CHARS:
            break

    return "\n".join(partes), ocr_parcial


def _sanitizar(texto: str) -> str:
    """Remove caracteres de controle e normaliza encoding UTF-8."""
    texto = unicodedata.normalize("NFC", texto)
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", texto)
    return texto.strip()


def _falha(flag: str, paginas: int) -> dict[str, object]:
    return {
        "texto": "",
        "paginas": paginas,
        "metodo_extracao": "nenhum",
        "flags": [flag],
    }
