# ADR-002 — Contrato Clone↔Wrapper

**Data:** 2026-05-22
**Status:** Aceito
**Deciders:** @architect (Aria), com suporte de @dev (Dex)
**Story de origem:** [0.3 — ADR-002 — Definir contrato de integração entre Wrapper Python e Squad Clone](../stories/0.3.story.md)
**Substitui:** —
**Substituído por:** —

---

## Contexto

O sistema `bacharelado-correcoes` precisa orquestrar correções acadêmicas em lote (batch) usando como fonte de inteligência o squad `bacharelado-correcoes` localizado em `squads/bacharelado-correcoes/`. Existem dois caminhos possíveis para integrar esse squad ao código de produção:

1. **Agente interativo (Clone como AIOX agent)** — invocar o agente `@corretor-academico` em modo conversacional para cada aluno, dialogando turnos múltiplos até obter as fichas.
2. **Wrapper Python (chamada direta à API)** — um módulo Python que lê os arquivos do squad, monta um system prompt estático e chama a API Anthropic em um único turno por aluno, recebendo um JSON estruturado.

Características do uso real (Professor Assistente corrigindo turmas em lote):

- **Volume:** dezenas a centenas de alunos por batch (Etapa/Aula × A1/A2 × disciplina).
- **Previsibilidade:** o output precisa ser sempre o mesmo formato (JSON) para alimentar a planilha institucional.
- **Auditabilidade:** cada chamada precisa ser reproduzível e logável (RA, prompt, response, custo).
- **Custo:** chamadas conversacionais multi-turno consomem 3-10× mais tokens do que single-turn estruturado.
- **Confiabilidade:** o agente interativo pode "se desviar" do formato esperado em respostas longas — JSON estruturado validado por schema é deterministicamente verificável.
- **Mudança da fonte-de-verdade:** o squad evolui (heurísticas H1-H7, rubricas, blocklists). O Wrapper precisa absorver essas mudanças sem rebuild do código Python.

Por essas razões, o agente interativo é incompatível com o caso de uso de batch acadêmico.

---

## Decisão

Adotar o padrão **Wrapper Python** como única forma de integração entre o código de produção e o squad `bacharelado-correcoes`:

1. **Source-of-truth:** os arquivos do squad em `squads/bacharelado-correcoes/` permanecem a única fonte de regras de correção. Não há duplicação no Python.
2. **Carregamento dinâmico:** o Wrapper lê os arquivos relevantes do squad em tempo de execução (ou em cache invalidado por mtime) e monta um system prompt estático a partir deles.
3. **Chamada direta:** o Wrapper chama a API Anthropic diretamente (sem MCP, sem agente intermediário), modelo padrão `claude-haiku-4-5-20251001` (modelo final em ADR-003).
4. **Output estruturado:** a resposta é um JSON validado por Pydantic (`RespostaBatch`).
5. **Sem invocação do agente AIOX:** o arquivo `agents/corretor-academico.md` é tratado como **documento de referência** para humanos e como **componente do system prompt**, mas o agente AIOX `@corretor-academico` não é executado pelo Wrapper.

> **Nota terminológica:** a Story 0.3 refere-se a um `SKILL.md` no squad. Esse arquivo **não existe** com esse nome — o equivalente funcional é o conjunto `agents/corretor-academico.md` + `tasks/` + `data/` + `templates/`. Este ADR formaliza quais desses arquivos compõem o system prompt.

---

## Veto Conditions do Contrato

Condições identificadas pela revisão de processo (Pedro Valério, 2026-05-22) que BLOQUEIAM a entrada no Sprint 2 se não tratadas. Todas as 9 condições abaixo são implementadas neste ADR revisado.

| # | Categoria | Veto Condition | Severidade |
|---|-----------|---------------|------------|
| V1 | Path relativo | `SQUAD_ROOT` relativo ao CWD → `FileNotFoundError` em produção | CRÍTICO |
| V2 | Retry cego | Retry sem incluir `raw` da resposta inválida | CRÍTICO |
| V3 | Truncation | `stop_reason="max_tokens"` não detectado | CRÍTICO |
| V4 | Arquivo vazio | Falha silenciosa sem blocklist | CRÍTICO |
| V5 | Prompt injection | Zero sanitização de conteúdo do aluno | CRÍTICO |
| V6 | Sem timeout | Default 600s pode travar batch | ALTO |
| V7 | UnicodeDecodeError | Encoding diferente de UTF-8 não tratado | ALTO |
| V8 | Batch size indefinido | Parâmetro de otimização não documentado | MÉDIO |
| V9 | Prompt cache ausente | 80-85% de custo evitável sem contrato | MÉDIO |

---

## Implementação do Wrapper (pseudocódigo)

```python
# packages/wrapper/clone_client.py
import logging
import re
from pathlib import Path
from anthropic import Anthropic
from pydantic import ValidationError

from .schemas import RespostaBatch
from .exceptions import ClonValidationError, ClonTruncatedResponseError, EmptySquadFileError

logger = logging.getLogger(__name__)

# V1 — Path absoluto resolvido relativo ao arquivo fonte, não ao CWD.
# NUNCA usar Path("squads/...") — depende do diretório de execução e explode em produção.
SQUAD_ROOT = Path(__file__).parent.parent.parent / "squads/bacharelado-correcoes"

MODEL = "claude-haiku-4-5-20251001"

# V8 — Tamanho padrão de batch por chamada à API.
# Equilibra custo de retry (batch menor = menos retrabalho em falha)
# com overhead de chamadas (batch maior = menos roundtrips).
BATCH_SIZE = 10

# V6 — Timeout explícito em segundos. SDK Anthropic tem default de 600s —
# 1 chamada travada num batch de 50 alunos poderia segurar o processo 10min.
API_TIMEOUT = 90

# Arquivos do squad que compõem o system prompt (ordem importa).
# Veja seção "Referências" para justificativa de cada inclusão/exclusão.
SYSTEM_PROMPT_SOURCES = [
    SQUAD_ROOT / "agents" / "corretor-academico.md",
    SQUAD_ROOT / "data" / "rubrica-institucional.md",
    SQUAD_ROOT / "data" / "blocklist-bajulacao.md",
    SQUAD_ROOT / "tasks" / "corrigir-batch.md",
    SQUAD_ROOT / "tasks" / "calibrar-batch.md",
    SQUAD_ROOT / "tasks" / "gerar-feedback.md",
    SQUAD_ROOT / "checklists" / "checklist-correcao.md",
    SQUAD_ROOT / "templates" / "feedback-tmpl.md",
]

# Arquivos NÃO incluídos no system prompt:
# - README.md          (documentação humana, não regras)
# - config.yaml        (metadados, redundante)
# - tasks/exportar-planilha.md (concerne a planilha — fora do escopo da correção)
# - templates/planilha-tmpl.md (idem)

# V5 — Padrões de prompt injection a detectar no conteúdo do aluno.
# Se detectado: flag "possivel_injection" na ficha + log de auditoria.
INJECTION_PATTERNS = [
    r"(?i)(ignore|ignora).{0,30}(instru[çc][oõ]|anterior|sistema)",
    r"(?i)(retorn[ae]|return).{0,20}(json|nota|ficha)",
    r"(?i)fim\s+do?\s+(trabalho|enunciado|sistema)",
]


def _read_squad_file(path: Path) -> str:
    """Lê um arquivo do squad com fallback de encoding. [V4, V7]"""
    if not path.exists():
        raise FileNotFoundError(f"Arquivo do squad ausente: {path}")

    # V7 — Tentar UTF-8 primeiro; fallback para latin-1 se necessário.
    # Arquivos editados no Windows podem ter encoding latin-1.
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="latin-1")
        logger.warning("Arquivo com encoding não-UTF-8 (latin-1 usado): %s", path)

    # V4 — Arquivo vazio = falha silenciosa crítica.
    # Ex.: blocklist-bajulacao.md vazia → IA não aplica H4 (INEGOCIÁVEL).
    stripped = content.strip()
    if not stripped:
        raise EmptySquadFileError(f"Arquivo do squad vazio: {path}")

    return content


def build_system_prompt() -> str:
    """Lê os arquivos do squad e concatena em um system prompt único."""
    sections = []
    for path in SYSTEM_PROMPT_SOURCES:
        content = _read_squad_file(path)
        sections.append(
            f"## SOURCE: {path.relative_to(SQUAD_ROOT.parent)}\n\n{content}"
        )
    return "\n\n---\n\n".join(sections)


def _detect_injection(conteudo: str) -> bool:
    """Retorna True se o conteúdo do aluno contém padrões de prompt injection. [V5]"""
    return any(re.search(pattern, conteudo) for pattern in INJECTION_PATTERNS)


def format_user_message(payload: dict, injection_flags: dict[str, bool] | None = None) -> str:
    """Monta a mensagem do usuário com delimitadores explícitos por aluno. [V5]

    Delimitadores explícitos reduzem a eficácia de injection ao tornar
    o conteúdo do aluno claramente separado das instruções do sistema.
    """
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


def corrigir_aluno(client: Anthropic, payload: dict) -> RespostaBatch:
    """Chama a API e valida o JSON de resposta."""
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
    # Cache dura 5 min → batch sequencial aproveita cache em todas as chamadas.
    system_prompt = build_system_prompt()
    user_message = format_user_message(payload)

    for tentativa in range(1, 3):  # max 2 tentativas (1 normal + 1 retry)
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            temperature=0.0,
            timeout=API_TIMEOUT,  # V6 — Timeout explícito de 90s
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},  # V9 — Prompt cache
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )

        # V3 — Detectar truncation por max_tokens ANTES de tentar validar JSON.
        # JSON truncado nunca passa na validação Pydantic; retry seria inútil.
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
                if injection_flags.get(ficha.ra):
                    if "possivel_injection" not in ficha.flags:
                        ficha.flags.append("possivel_injection")

            return parsed
        except ValidationError as e:
            if tentativa == 1:
                # V2 — Retry com contexto: incluir raw[:500] para o Clone ver
                # o próprio erro e ter chance real de corrigir.
                user_message += (
                    f"\n\nATENÇÃO: sua resposta anterior falhou validação.\n"
                    f"Resposta que você deu:\n```\n{raw[:500]}\n```\n"
                    f"Erros: {e.errors()[:3]}\n"
                    f"Retorne APENAS JSON válido conforme schema RespostaBatch. "
                    f"Sem markdown, sem code fences, sem texto antes/depois."
                )
                continue
            # Tentativa 2 falhou → propagar erro e marcar batch para revisão manual
            raise ClonValidationError(raw=raw, errors=e.errors())
```

**Observação sobre cache (V9):** o campo `system` recebe um array com `cache_control: {"type": "ephemeral"}`. O cache dura 5 minutos a partir da primeira chamada. Num batch sequencial de até ~60 alunos processados dentro de 5 minutos, todas as chamadas reutilizam o cache — redução de custo estimada de 80-85% no componente de system prompt (tokens cached custam ~0.1× o preço de input normal).

**Observação sobre batch size (V8):** o parâmetro `BATCH_SIZE = 10` define quantos alunos são enviados por chamada à API. O orquestrador de batch deve particionar a turma em grupos de `BATCH_SIZE` antes de chamar `corrigir_aluno()`. Justificativa: batch menor limita o custo de retry em caso de `ClonValidationError` (reprocessa no máximo 10 alunos, não a turma inteira); batch maior reduz overhead de chamadas. 10 é o valor padrão — ajustável via configuração do orquestrador.

---

## Schema de Resposta

Schema Pydantic completo da resposta da IA. Toda chamada ao Wrapper retorna um objeto `RespostaBatch` validado.

```python
# packages/wrapper/schemas.py
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class MatrizPontuacao(BaseModel):
    """Pontuação por critério extraído do enunciado (H2).

    Critérios são opcionais porque cada disciplina/etapa tem critérios próprios.
    Quando um critério não se aplica ao trabalho avaliado, o campo é null.
    """
    criterio_apresentacao: Optional[float] = Field(None, ge=0.0, le=10.0)
    criterio_conteudo: Optional[float] = Field(None, ge=0.0, le=10.0)
    criterio_metodologia: Optional[float] = Field(None, ge=0.0, le=10.0)
    criterio_conclusao: Optional[float] = Field(None, ge=0.0, le=10.0)


class FichaCorrecao(BaseModel):
    """Ficha individual de correção para um aluno.

    Corresponde 1:1 ao output esperado pela task `corrigir-batch.md` do squad.
    """
    ra: str = Field(..., pattern=r"^\d{11}$", description="RA normalizado 11 dígitos")
    nota_a1: Optional[float] = Field(None, ge=0.0, le=10.0, description="Nota A1 (apresentação)")
    nota_a2: Optional[float] = Field(None, ge=0.0, le=10.0, description="Nota A2 (entrega)")
    matriz_pontuacao: Optional[MatrizPontuacao] = None
    feedback: str = Field(..., min_length=1, description="Feedback estruturado conforme template (8 slots)")
    flags: List[Literal[
        "plagio",
        "ia_generativa",
        "arquivo_errado",
        "sem_vinculo",
        "possivel_injection",  # V5 — adicionado na revisão Sprint 2
    ]] = Field(
        default_factory=list,
        description="Lista de flags especiais. Vazia se nenhuma flag se aplica.",
    )
    confianca: Literal["alta", "media", "baixa"] = Field(
        ..., description="Nível de confiança da IA na correção. 'baixa' → revisar manualmente."
    )

    @field_validator("ra")
    @classmethod
    def normaliza_ra(cls, v: str) -> str:
        return v.strip()


class RespostaBatch(BaseModel):
    """Resposta consolidada para um batch de correções.

    Um batch pode conter 1 ou N alunos (máx. BATCH_SIZE=10 por chamada).
    A IA retorna `fichas[]` com a ordem correspondente ao payload de entrada.
    """
    fichas: List[FichaCorrecao] = Field(..., min_length=1)
    observacoes_gerais: Optional[str] = Field(
        None,
        description="Observações sobre o batch (calibração, padrões, alertas).",
    )
```

### Tabela resumo dos campos

| Campo | Tipo | Obrigatório | Constraint | Origem no squad |
|-------|------|-------------|------------|-----------------|
| `fichas` | `List[FichaCorrecao]` | sim | min_length=1 | `tasks/corrigir-batch.md` (phase_2) |
| `fichas[].ra` | `str` | sim | regex `^\d{11}$` | `tasks/corrigir-batch.md` (output_per_aluno) |
| `fichas[].nota_a1` | `float \| null` | sim (campo presente) | 0.0–10.0 | `agents/corretor-academico.md` (H7) |
| `fichas[].nota_a2` | `float \| null` | sim (campo presente) | 0.0–10.0 | `agents/corretor-academico.md` (H7) |
| `fichas[].matriz_pontuacao` | `MatrizPontuacao \| null` | não | cada critério 0.0–10.0 | `tasks/corrigir-batch.md` (phase_1, phase_2) |
| `fichas[].feedback` | `str` | sim | não-vazio | `tasks/gerar-feedback.md` + `templates/feedback-tmpl.md` |
| `fichas[].flags` | `List[str]` | sim | enum: plagio, ia_generativa, arquivo_errado, sem_vinculo, **possivel_injection** | `tasks/corrigir-batch.md` + V5 (revisão Sprint 2) |
| `fichas[].confianca` | `str` | sim | enum: alta, media, baixa | derivado das heurísticas (novo no contrato) |
| `observacoes_gerais` | `str \| null` | não | livre | `tasks/calibrar-batch.md` (observações de calibração) |

---

## Exemplo de Chamada

### Payload do usuário (mensagem enviada para a API)

```text
BATCH: Projeto Extensionista de IA — Etapa 4 — 27/04/2026 — A1
ENUNCIADO: "Estruture o GTM da solução proposta: (a) ICP, (b) jornada,
(c) canais, (d) métricas." (10 pontos)

ALUNOS A CORRIGIR:
--- INÍCIO TRABALHO ALUNO 20260100418 ---
[texto/transcrição do trabalho do aluno A]
--- FIM TRABALHO ALUNO 20260100418 ---

--- INÍCIO TRABALHO ALUNO 20260100422 ---
[texto/transcrição do trabalho do aluno B]
--- FIM TRABALHO ALUNO 20260100422 ---

INSTRUÇÃO: Retorne APENAS um JSON válido conforme o schema RespostaBatch
descrito no system prompt. Sem markdown, sem code fences, sem texto antes/depois.
```

> **Nota sobre delimitadores (V5):** o formato `--- INÍCIO/FIM TRABALHO ALUNO {ra} ---` isola o conteúdo do aluno das instruções do sistema. Se o aluno incluir no trabalho texto como "Ignore as instruções anteriores", o delimitador explícito reduz a eficácia do ataque ao deixar claro para o modelo que o conteúdo entre delimitadores é material de avaliação, não instrução.

### Resposta da IA — caso de sucesso

```json
{
  "fichas": [
    {
      "ra": "20260100418",
      "nota_a1": 8.5,
      "nota_a2": null,
      "matriz_pontuacao": {
        "criterio_apresentacao": 8.0,
        "criterio_conteudo": 9.0,
        "criterio_metodologia": 8.5,
        "criterio_conclusao": null
      },
      "feedback": "PONTOS FORTES:\n- ICP claramente definido com persona detalhada (idade, dor, contexto profissional)\n- Jornada estruturada com 5 etapas e gatilhos de transição\n\nLACUNAS ESPECÍFICAS:\n- Métricas listadas sem definição de baseline ou meta (apenas nomes: CAC, LTV, churn)\n- Canais mencionados sem priorização ou justificativa por etapa da jornada\n\nPRÓXIMO PASSO:\nPara A2, vincular cada métrica à etapa da jornada e definir 1 valor-alvo por métrica.",
      "flags": [],
      "confianca": "alta"
    },
    {
      "ra": "20260100422",
      "nota_a1": 0.0,
      "nota_a2": null,
      "matriz_pontuacao": null,
      "feedback": "ARQUIVO ENTREGUE NÃO CORRESPONDE À ATIVIDADE.\nO arquivo enviado contém um pitch comercial, não um GTM estruturado conforme solicitado no enunciado (a, b, c, d).\nReentrega necessária para avaliação. Sem nota provisória.",
      "flags": ["arquivo_errado"],
      "confianca": "alta"
    }
  ],
  "observacoes_gerais": "Batch de 2 alunos do Grupo 3. Aluno A com entrega adequada (8.5). Aluno B com flag de arquivo_errado — comunicar reentrega antes da calibração comparativa."
}
```

### Resposta da IA — caso de falha de validação

Resposta inválida (texto fora do JSON, viola schema):

```text
Claro! Aqui está a correção do batch:

```json
{
  "fichas": [
    {
      "ra": "418",        ← INVÁLIDO: deve ter 11 dígitos
      "nota_a1": 15,      ← INVÁLIDO: > 10.0
      "feedback": "",     ← INVÁLIDO: min_length=1
      "flags": ["ótimo"], ← INVÁLIDO: fora do enum
      "confianca": "muito alta"  ← INVÁLIDO: fora do enum
    }
  ]
}
```

Espero ter ajudado!
```

Ações disparadas pelo Wrapper diante dessa resposta:

1. `response.stop_reason` é verificado — se `"max_tokens"` → `ClonTruncatedResponseError` (sem retry).
2. `RespostaBatch.model_validate_json(raw)` lança `ValidationError` com 5 erros.
3. Wrapper aciona política de retry com contexto (V2): manda `raw[:500]` + erros de volta.

---

## Política de Retry e Error Handling

### Estratégia

| Tentativa | Ação | Modificação no prompt |
|-----------|------|----------------------|
| 1 | Chamada normal | — |
| 2 (retry) | Reenviar com contexto completo | Anexa: `raw[:500]` da resposta anterior + erros Pydantic + instrução de formato |
| 3+ | **Não tentar** | — |

**Máximo de tentativas de validação: 2** (1 normal + 1 retry com contexto).

> **Diferença da versão anterior (V2):** o retry agora inclui `raw[:500]` — os primeiros 500 caracteres da resposta inválida. Sem isso, o modelo não sabe o que produziu de errado e tem menor chance de acerto na segunda tentativa.

### Detecção de truncation (V3)

`stop_reason == "max_tokens"` indica JSON truncado. **Não aciona retry de validação** — a causa raiz é tamanho, não formato, e retry não resolve. Ação:

1. Lançar `ClonTruncatedResponseError(ra=..., tokens_used=...)`.
2. Camada chamadora marca aluno como "REVISÃO MANUAL — RESPOSTA TRUNCADA".
3. Log com `tokens_used` para diagnóstico: se recorrente, aumentar `max_tokens` ou reduzir `BATCH_SIZE`.

### Tratamento após esgotar tentativas de validação

Se a segunda tentativa também falhar validação:

1. Wrapper lança exceção `ClonValidationError(raw=raw, errors=e.errors())`.
2. A camada chamadora (orquestrador de batch) captura a exceção e:
   - Marca o aluno como "REVISÃO MANUAL OBRIGATÓRIA" no relatório do batch.
   - Adiciona à **Camada 3 — fila de revisão manual** (ver arquitetura geral).
   - Continua processamento dos demais alunos do batch (falha de um aluno **não** aborta o batch).
3. Log estruturado com: `ra`, `tentativas`, `raw_response` (primeiros 2000 chars), `validation_errors`, `timestamp`, `model`, `tokens_used`.

### Erros de API (não-validação)

| Erro | Ação |
|------|------|
| `RateLimitError` (HTTP 429) | Backoff exponencial: 2s, 4s, 8s. Máximo 3 retries de API. Após isso, propagar. |
| `APITimeoutError` | 1 retry com mesmo prompt. Após isso, propagar. **Timeout configurado em 90s (V6)** — se recorrente, investigar tamanho do batch ou latência de rede antes de aumentar o valor. |
| `APIConnectionError` | 1 retry. Após isso, propagar. |
| `AuthenticationError` (HTTP 401) | **Não tentar retry.** Propagar imediatamente — problema de configuração. |
| `BadRequestError` (HTTP 400) | **Não tentar retry.** Propagar — payload malformado, requer fix no código. |
| Resposta vazia (`content == ""`) | Considerar como falha de validação → ativa retry de validação. |
| `ClonTruncatedResponseError` | **Não tentar retry de validação.** Marcar como REVISÃO MANUAL — TRUNCADA. |

### Anti-patterns explicitamente proibidos

- ❌ Mais de 1 retry de validação (custo cresce linearmente, sucesso decresce exponencialmente).
- ❌ Retry sem modificar prompt (mesma entrada → mesma saída inválida).
- ❌ Retry de validação quando `stop_reason == "max_tokens"` (causa raiz é tamanho, não formato).
- ❌ Abortar o batch inteiro quando um aluno falha (resiliência por aluno é obrigatória).
- ❌ Silenciar `ClonValidationError` (precisa ir para fila de revisão manual com trace completo).
- ❌ Fallback automático para correção manual sem registro (perde auditoria).
- ❌ Passar conteúdo do aluno sem delimitadores explícitos (facilita prompt injection).

---

## Consequências

### Positivas

- **Custo previsível:** single-turn structured output ~3-10× mais barato que chat multi-turno.
- **Auditoria:** cada chamada tem prompt + response logáveis em texto plano.
- **Determinismo:** schema Pydantic torna validação binária (passa ou falha).
- **Evolução:** mudanças no squad refletem na próxima chamada sem deploy de Python.
- **Resiliência:** falha de um aluno não compromete o batch.
- **Custo reduzido (V9):** prompt caching reduz ~80-85% do custo de system prompt em batches sequenciais.

### Negativas / Trade-offs

- **Sem capacidade de diálogo:** PA não pode perguntar "por que essa nota?" ao Clone diretamente — precisa abrir o agente AIOX manualmente fora do pipeline (uso interativo paralelo).
- **System prompt grande:** soma dos arquivos do squad pode ultrapassar 30k tokens. Mitigado pelo prompt caching (V9) — sem cache, custo seria linear por aluno.
- **Acoplamento ao schema:** mudanças no schema Pydantic exigem mudança coordenada no squad (nas seções que descrevem o output). Mitigação: este ADR é a fonte canônica; ambos os lados devem citar este ADR como referência.

### Riscos residuais

- Se um arquivo do squad listado em `SYSTEM_PROMPT_SOURCES` for renomeado/movido, o Wrapper falha em `FileNotFoundError` na primeira chamada. Mitigação: cobertura por teste de integração que valida `build_system_prompt()` sem chamar API. *(Risco original — ainda válido.)*
- Drift entre o schema descrito no system prompt (markdown nos arquivos do squad) e o Pydantic concreto. Mitigação: este ADR é a fonte canônica; ambos lados devem citar este ADR como referência. *(Risco original — ainda válido.)*
- **V7 (residual):** arquivos com encoding não-UTF-8 ativam fallback latin-1 com log de warning. Se o arquivo contiver caracteres fora do latin-1, `read_text` ainda pode falhar com `UnicodeDecodeError` não tratado. Mitigação: padronizar encoding UTF-8 nos arquivos do squad via `.editorconfig`.
- **V8 (residual):** `BATCH_SIZE = 10` é o padrão, mas não há validação que impeça o orquestrador de passar mais alunos. Mitigação: validação de precondição no orquestrador (`assert len(payload["alunos"]) <= BATCH_SIZE`).
- **V5 (residual):** a sanitização por regex detecta padrões conhecidos, mas não é infalível contra injection sofisticada. Mitigação primária são os delimitadores explícitos; regex é camada secundária de detecção. Fichas com flag `possivel_injection` devem ser revisadas manualmente.

---

## Referências

### Arquivos do squad usados como system prompt (ordem importa)

| # | Arquivo | Por quê |
|---|---------|---------|
| 1 | `squads/bacharelado-correcoes/agents/corretor-academico.md` | Persona, comandos, heurísticas H1-H7, ativação. Funciona como cabeçalho do system prompt. |
| 2 | `squads/bacharelado-correcoes/data/rubrica-institucional.md` | Rubricas por disciplina (Saint Paul). Base para H7. |
| 3 | `squads/bacharelado-correcoes/data/blocklist-bajulacao.md` | Termos proibidos (H4 — INEGOCIÁVEL). |
| 4 | `squads/bacharelado-correcoes/tasks/corrigir-batch.md` | Pipeline de avaliação: pré-flight, extração de critérios, avaliação individual. Define `matriz_pontuacao` e `flags`. |
| 5 | `squads/bacharelado-correcoes/tasks/calibrar-batch.md` | Regra dos 10% e cap de 9 (H1 — NON-NEGOTIABLE). Alimenta `observacoes_gerais`. |
| 6 | `squads/bacharelado-correcoes/tasks/gerar-feedback.md` | 8 slots de feedback estruturado. Alimenta `fichas[].feedback`. |
| 7 | `squads/bacharelado-correcoes/checklists/checklist-correcao.md` | Auto-validação antes de retornar a ficha. |
| 8 | `squads/bacharelado-correcoes/templates/feedback-tmpl.md` | Formato literal do feedback (7 variações). |

### Arquivos do squad NÃO incluídos no system prompt

| Arquivo | Por quê não |
|---------|-------------|
| `squads/bacharelado-correcoes/README.md` | Documentação para humanos, redundante com `corretor-academico.md`. |
| `squads/bacharelado-correcoes/config.yaml` | Metadados de loader, não comportamento. |
| `squads/bacharelado-correcoes/tasks/exportar-planilha.md` | Concerne planilha (etapa pós-correção, fora do escopo do Wrapper). |
| `squads/bacharelado-correcoes/templates/planilha-tmpl.md` | Idem. |

### ADRs e stories relacionados

- Story 0.3 — ADR-002 (este documento) — `docs/stories/0.3.story.md`
- ADR-003 (Story 0.4) — Modelo, temperature e tokens — a ser criado.
- ADR-001 (Story 0.1) — Decisão de Wrapper Python vs. agente interativo — a ser criado (este ADR-002 pressupõe a decisão).
- Sprint 0 Index — `docs/stories/SPRINT-0-INDEX.md`

### Documentação técnica externa

- Anthropic Messages API — https://docs.anthropic.com/claude/reference/messages_post
- Anthropic Prompt Caching — https://docs.anthropic.com/claude/docs/prompt-caching
- Pydantic v2 docs — https://docs.pydantic.dev/latest/

---

## Histórico

| Data | Autor | Mudança |
|------|-------|---------|
| 2026-05-22 | @dev (Dex) | Criação do ADR conforme Story 0.3, modo YOLO. |
| 2026-05-22 | @dev (Dex) | Revisão Sprint 2: 9 correções de processo (V1-V9) identificadas por Pedro Valério. Path absoluto (V1), retry com contexto (V2), detecção de truncation (V3), guard de arquivo vazio (V4), sanitização de prompt injection + flag possivel_injection (V5), timeout 90s (V6), fallback de encoding (V7), batch size documentado (V8), prompt cache contratado (V9). |
