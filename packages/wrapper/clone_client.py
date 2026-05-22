"""Wrapper Python do squad corretor-academico (ADR-002).

Implementa o pseudocódigo canônico da seção "Implementação do Wrapper" do ADR-002,
cobrindo todas as 9 veto conditions (V1-V9) e ADR-003 (temperature=0).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from packages.wrapper.exceptions import (
    ClonTruncatedResponseError,
    ClonValidationError,
    EmptySquadFileError,
)
from packages.wrapper.schemas import RespostaBatch

logger = logging.getLogger(__name__)

# V1 — Path absoluto resolvido relativo ao __file__, NUNCA ao CWD.
SQUAD_ROOT = Path(__file__).parent.parent.parent / "squads/bacharelado-correcoes"

MODEL = "claude-haiku-4-5-20251001"  # ADR-003

# V8 — Equilíbrio custo de retry (batch menor = menos retrabalho em falha)
# com overhead de chamadas (batch maior = menos roundtrips).
BATCH_SIZE = 10

# V6 — SDK Anthropic tem default de 600s — 1 chamada travada pode segurar batch 10min.
API_TIMEOUT = 90

# Arquivos do squad que compõem o system prompt (ordem importa — ADR-002).
SYSTEM_PROMPT_SOURCES: list[Path] = [
    SQUAD_ROOT / "agents" / "corretor-academico.md",
    SQUAD_ROOT / "data" / "rubrica-institucional.md",
    SQUAD_ROOT / "data" / "blocklist-bajulacao.md",
    SQUAD_ROOT / "tasks" / "corrigir-batch.md",
    SQUAD_ROOT / "tasks" / "calibrar-batch.md",
    SQUAD_ROOT / "tasks" / "gerar-feedback.md",
    SQUAD_ROOT / "checklists" / "checklist-correcao.md",
    SQUAD_ROOT / "templates" / "feedback-tmpl.md",
]

# V5 — Padrões de prompt injection a detectar no conteúdo do aluno.
INJECTION_PATTERNS = [
    r"(?i)(ignore|ignora).{0,30}(instru[çc][oõ]|anterior|sistema)",
    r"(?i)(retorn[ae]|return).{0,20}(json|nota|ficha)",
    r"(?i)fim\s+do?\s+(trabalho|enunciado|sistema)",
]


def _read_squad_file(path: Path) -> str:
    """Lê arquivo do squad com fallback de encoding. [V4, V7]"""
    if not path.exists():
        raise FileNotFoundError(f"Arquivo do squad ausente: {path}")

    # V7 — Tentar UTF-8 primeiro; fallback para latin-1 se necessário.
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="latin-1")
        logger.warning("Arquivo com encoding não-UTF-8 (latin-1 usado): %s", path)

    # V4 — Arquivo vazio = falha silenciosa crítica (ex.: blocklist vazia → H4 ignorado).
    if not content.strip():
        raise EmptySquadFileError(f"Arquivo do squad vazio: {path}")

    return content


def build_system_prompt() -> str:
    """Lê os arquivos do squad e concatena em system prompt único."""
    sections = []
    for path in SYSTEM_PROMPT_SOURCES:
        content = _read_squad_file(path)
        try:
            label = path.relative_to(SQUAD_ROOT.parent)
        except ValueError:
            label = path
        sections.append(f"## SOURCE: {label}\n\n{content}")
    return "\n\n---\n\n".join(sections)


def _detect_injection(conteudo: str) -> bool:
    """Retorna True se o conteúdo contém padrões de prompt injection. [V5]"""
    return any(re.search(pattern, conteudo) for pattern in INJECTION_PATTERNS)


def format_user_message(
    payload: dict[str, Any],
    injection_flags: dict[str, bool] | None = None,
) -> str:
    """Monta a mensagem do usuário com delimitadores explícitos por aluno. [V5]"""
    lines = [
        f"BATCH: {payload['metadata']}",
        f"ENUNCIADO: {payload['enunciado']}",
        "",
        "ALUNOS A CORRIGIR:",
    ]
    for aluno in payload["alunos"]:
        ra = aluno["ra"]
        conteudo = aluno["conteudo"]
        lines.append(f"--- INÍCIO TRABALHO ALUNO {ra} ---")
        lines.append(conteudo)
        lines.append(f"--- FIM TRABALHO ALUNO {ra} ---")
        lines.append("")

    lines.append(
        "INSTRUÇÃO: Retorne APENAS um JSON válido conforme o schema RespostaBatch "
        "descrito no system prompt. Sem markdown, sem code fences, sem texto antes/depois."
    )
    return "\n".join(lines)


def corrigir_aluno(client: Any, payload: dict[str, Any]) -> RespostaBatch:
    """Chama a API Anthropic e valida o JSON de resposta. [V2, V3, V5, V6, V9]"""
    # V5 — Verificar injection em todos os trabalhos antes de montar o prompt.
    injection_flags: dict[str, bool] = {}
    for aluno in payload.get("alunos", []):
        ra = aluno.get("ra", "unknown")
        if _detect_injection(aluno.get("conteudo", "")):
            injection_flags[ra] = True
            logger.warning(
                "Possível prompt injection detectado no trabalho do aluno RA=%s — "
                "flag 'possivel_injection' será adicionada à ficha.",
                ra,
            )

    # V9 — Prompt cache: system prompt fixo com cache_control ephemeral.
    system_prompt = build_system_prompt()
    user_message = format_user_message(payload, injection_flags)

    for tentativa in range(1, 3):  # max 2 tentativas (1 normal + 1 retry com contexto)
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            temperature=0.0,  # ADR-003 — correção = determinístico
            timeout=API_TIMEOUT,  # V6
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},  # V9
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )

        # V3 — Detectar truncation ANTES de tentar validar JSON (JSON truncado nunca passa).
        if response.stop_reason == "max_tokens":
            raise ClonTruncatedResponseError(
                ra=payload.get("alunos", [{}])[0].get("ra"),
                tokens_used=response.usage.output_tokens,
            )

        raw = response.content[0].text
        try:
            parsed = RespostaBatch.model_validate_json(raw)

            # V5 — Pós-processamento: adicionar flag de injection onde detectado.
            for ficha in parsed.fichas:
                if injection_flags.get(ficha.ra) and "possivel_injection" not in ficha.flags:
                    ficha.flags.append("possivel_injection")

            return parsed

        except ValidationError as e:  # AC-11 — except narrowado (MNT-001)
            if tentativa == 1:
                # V2 — Retry com contexto: raw[:500] + erros Pydantic.
                user_message += (
                    f"\n\nATENÇÃO: sua resposta anterior falhou validação.\n"
                    f"Resposta que você deu:\n```\n{raw[:500]}\n```\n"
                    f"Erros: {e.errors()[:3]}\n"
                    f"Retorne APENAS JSON válido conforme schema RespostaBatch. "
                    f"Sem markdown, sem code fences, sem texto antes/depois."
                )
                continue
            raise ClonValidationError(raw=raw, errors=e.errors()) from e

    # Nunca alcançado — loop sempre retorna ou levanta na tentativa 2.
    raise ClonValidationError(raw="", errors=[])
