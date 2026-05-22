# Sprint 3 — Interface de validação do PA: Índice de Stories

**Projeto:** Corretor Acadêmico
**Sprint:** 3
**Objetivo do Sprint:** Implementar a interface Streamlit completa para o Professor Assistente (PA) — upload da planilha, acompanhamento do batch em tempo real, validação interativa das notas com alertas de plágio/grupos (Progressive Disclosure), e exportação para Excel.
**Status:** Planejado
**Criado em:** 2026-05-22
**Criado por:** @sm (River)
**Design:** @oalanicolas (Alan Nicolas) — fluxo de 4 telas com Progressive Disclosure
**Pré-requisito:** Sprint 2 completo (Stories 2.0–2.6 Done)

---

## Stories do Sprint

| ID | Título | Complexidade | Status | Dependências | Arquivos Principais |
|----|--------|-------------|--------|--------------|---------------------|
| [3.0](./3.0.story.md) | Tela de upload e configuração do batch | M | Draft | Sprint 2 completo | `src/ui/upload_screen.py` |
| [3.1](./3.1.story.md) | Barra de progresso do batch (real-time via batch_state) | M | Draft | Story 3.0 | `src/ui/progress_screen.py` |
| [3.2](./3.2.story.md) | Tabela de validação com grupos e plágio (Progressive Disclosure) | L | Draft | Story 3.1 | `src/ui/validation_screen.py` |
| [3.3](./3.3.story.md) | Exportação para Excel com decisões do PA | S | Draft | Story 3.2 | `src/ui/export_screen.py`, `src/ui/excel_builder.py` |

---

## Fluxo de Telas (design @oalanicolas)

```
Tela 1 (Story 3.0)          Tela 2 (Story 3.1)
Upload + Configuração   →   Progresso do Batch
      ↓                           ↓
 [Validação OK]            [Batch concluído]
                                  ↓
                     Tela 3 (Story 3.2)
                     Tabela de Validação
                     (Progressive Disclosure)
                           ↓
                  [Todos revisados]
                           ↓
                  Tela 4 (Story 3.3)
                  Exportação para Excel
```

---

## Princípios de Design do Sprint 3

### Progressive Disclosure (3 níveis)

Aplicado na tabela de validação (Story 3.2) para evitar sobrecarga cognitiva do PA:

| Nível | O que é exibido | Trigger |
|-------|----------------|---------|
| **Level 0** | RA, notas, Δ, badge status, ícones de alerta | Sempre visível |
| **Level 1** | razao_confianca + feedback resumido + botões de decisão | Clicar "👁 Revisar" |
| **Level 2** | Pares de plágio detalhados OU detalhes de grupo | Clicar "Ver detalhes" dentro do Level 1 |

### Garantia ADR-006 (inegociável)

O sistema **NUNCA modifica notas automaticamente**. Detectores de plágio e grupos são **informativos**. Toda decisão de nota é do PA.

### Garantia ADR-004 (LGPD)

- Nomes de alunos: usados apenas para preview e Excel final (nunca em logs, nunca na API)
- Sidebar: exibe somente contagens agregadas, sem RAs individuais
- Exportação Excel: processamento 100% local, sem chamadas externas

---

## Padrões Obrigatórios do Sprint 3

### Módulo `src.ui`

Todos os componentes de UI do Sprint 3 residem em `src/ui/`. Criar `src/ui/__init__.py` vazio na Story 3.0.

### Separação UI ↔ Lógica

Cada tela Streamlit deve ter suas funções de lógica pura em módulo separado ou claramente identificadas para facilitar testes sem contexto Streamlit:

```python
# PADRÃO OBRIGATÓRIO — função pura, testável sem Streamlit
def construir_tabela(fichas: list[dict], decisoes: dict) -> pd.DataFrame:
    ...

# SEPARADA — função que usa st.*
def render_tabela(df: pd.DataFrame) -> None:
    st.dataframe(df)
```

### Testabilidade sem Streamlit

Os testes unitários das telas (`test_upload_screen.py`, `test_progress_screen.py`, `test_validation_screen.py`, `test_export_screen.py`) DEVEM testar apenas as funções puras — sem instanciar `streamlit` nem usar `AppTest`. Funções que chamam `st.*` ficam fora da cobertura de testes unitários.

### session_state como contrato entre telas

| Chave | Produzida por | Consumida por |
|-------|--------------|---------------|
| `batch_config` | Story 3.0 | Story 3.1 |
| `batch_results` | Story 3.1 | Story 3.2 |
| `decisoes` | Story 3.2 | Story 3.3 |

Cada tela DEVE verificar a presença da chave que consome antes de renderizar — e exibir `st.error` + link de retorno se ausente.

---

## Referências Cruzadas

| Módulo / ADR | Stories do Sprint 3 que consomem |
|-------------|----------------------------------|
| `src/batch/batch_processor.py` — `processar_batch()` | 3.1 |
| `src/batch/batch_processor.py` — `estimar_custo_brl()` | 3.0 |
| `src/batch/calibrator.py` — `calibrar_batch()` | 3.1 |
| `src/batch/plagiarism_detector.py` — `detectar_plagio_no_batch()` | 3.1 (executa), 3.2 (exibe) |
| `src/batch/group_detector.py` — `detectar_grupos_candidatos()` | 3.1 (executa), 3.2 (exibe) |
| `src/batch/batch_state.py` | 3.1 (polling de progresso) |
| `packages/wrapper/schemas.py` — `FichaCorrecao` | 3.2 |
| ADR-004 — LGPD / Retenção Zero | 3.0, 3.2, 3.3 |
| ADR-005 — Orçamento | 3.0 (estimativa), 3.1 (OrcamentoExcedidoError) |
| ADR-006 — Plágio | 3.2 (exibição informativa, sem modificar notas) |

---

_Sprint 3 Index criado por @sm (River) em 2026-05-22_
_Design de UX: @oalanicolas (Alan Nicolas) — sessão de 2026-05-22_
