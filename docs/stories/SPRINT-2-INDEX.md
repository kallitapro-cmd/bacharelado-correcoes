# Sprint 2 — Pipeline de batch de correção: Índice de Stories

**Projeto:** Corretor Acadêmico
**Sprint:** 2
**Objetivo do Sprint:** Implementar o pipeline completo de correção em lote — Wrapper Python que carrega o squad como system prompt, chama a API Anthropic, valida o JSON com Pydantic e alimenta a planilha institucional.
**Status:** Planejado
**Criado em:** 2026-05-22
**Criado por:** @sm (River)
**Pré-requisito:** Sprint 1 completo (12 stories Done)

---

## Stories do Sprint

| ID | Título | Complexidade | Status | Dependências | Arquivos Principais |
|----|--------|-------------|--------|--------------|---------------------|
| [2.0](./2.0.story.md) | Testes unitários de `clone_client.py` — cobertura V3/V4/V5 | S | Ready | Sprint 1 completo | `tests/unit/test_clone_client.py` |
| [2.1](./2.1.story.md) | Implementar `clone_client.py` — Wrapper Python do squad | M | Draft | 2.0 (Ready) | `packages/wrapper/clone_client.py`, `exceptions.py`, `schemas.py` |
| [2.2](./2.2.story.md) | Implementar `batch_processor.py` — Orquestrador de lotes | M | Draft | Story 2.1 (clone_client.py) | `src/batch/batch_processor.py`, `src/batch/exceptions.py` |

> **Nota:** Stories são adicionadas ao índice conforme o backlog é expandido.

---

## Primeira Story: 2.0 é gate de entrada

A Story 2.0 cobre os testes unitários obrigatórios de `clone_client.py` identificados pelo qa-gate do ADR-002. Deve ser concluída **antes ou em paralelo** com a story que implementa `clone_client.py`.

**Origem:** Recomendação do @qa (Quinn) no qa-gate do ADR-002 revisado (Sprint 2):
> "Registrar os 5 casos de teste unitário como task no Sprint 2 antes de implementar `clone_client.py`. Os testes de `build_system_prompt()` podem ser executados sem API key e devem fazer parte do CI."

---

## Padrões Obrigatórios do Sprint 2

### sqlite3 — Estado Efêmero de Sessão

Todo uso de `sqlite3` no Sprint 2 DEVE incluir o comentário abaixo na linha de definição do path do banco:

```python
# EFÊMERO: dados perdidos ao reiniciar sessão — comportamento esperado (ADR-004)
DB_PATH = Path("/tmp/batch_state.db")  # NUNCA usar caminho relativo ao projeto
```

**Motivo:** o Streamlit Cloud free tier usa filesystem efêmero destruído a cada redeploy. sqlite3 é usado exclusivamente como estado intermediário de sessão de batch — não como persistência cross-session. Usar `/tmp/` é intencional.

**Anti-padrão proibido:**
```python
# ERRADO — sobrevive ao redeploy apenas localmente; perde dados em produção
DB_PATH = Path("batch_state.db")
```

---

## Referências Cruzadas com ADRs

| ADR | Stories que implementam |
|-----|------------------------|
| ADR-002 — Contrato Clone↔Wrapper (revisado Sprint 2) | 2.0 (testes V3/V4/V5), 2.1 (implementação clone_client.py — V1-V9) |
| ADR-003 — Política de Temperature | 2.1 (temperature=0.0 na fase de correção) |

---

_Sprint 2 Index criado por @sm (River) em 2026-05-22_
