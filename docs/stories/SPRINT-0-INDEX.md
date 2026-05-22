# Sprint 0 — ADRs (pré-código): Índice de Stories

**Projeto:** Corretor Acadêmico
**Sprint:** 0
**Objetivo do Sprint:** Tomar e documentar todas as decisões de arquitetura necessárias antes do primeiro commit de código. Ao final do Sprint 0, a equipe deve ter clareza total sobre: normalização de RA, contrato com a IA, política de temperatura, privacidade/LGPD, orçamento e detecção de plágio.
**Status:** Draft
**Criado em:** 2026-05-22
**Criado por:** @sm (River)

---

## Stories do Sprint

| ID | Título | Complexidade | Status | Dependências | Artefato Gerado |
|----|--------|-------------|--------|--------------|-----------------|
| [0.1](./0.1.story.md) | Coletar e validar fixtures reais do PA | S | Draft | nenhuma | `docs/fixtures/` |
| [0.2](./0.2.story.md) | ADR-001 — Normalização de RA | S | Draft | 0.1 | `docs/decisions/ADR-001-formato-ra.md` + correção bug |
| [0.3](./0.3.story.md) | ADR-002 — Contrato Clone↔Wrapper | M | Draft | nenhuma | `docs/decisions/ADR-002-clone-contract.md` |
| [0.4](./0.4.story.md) | ADR-003 — Política de Temperature | S | Draft | nenhuma | `docs/decisions/ADR-003-temperature-policy.md` |
| [0.5](./0.5.story.md) | ADR-004 — LGPD e Retenção Zero | S | Draft | nenhuma | `docs/decisions/ADR-004-lgpd-retention.md` |
| [0.6](./0.6.story.md) | ADR-005 — Orçamento e Hard Limit | S | Draft | nenhuma | `docs/decisions/ADR-005-budget-policy.md` |
| [0.7](./0.7.story.md) | ADR-006 — Política de Plágio | S | Draft | nenhuma | `docs/decisions/ADR-006-plagio-policy.md` |

---

## Sequência Recomendada de Execução

O Sprint 0 tem poucas dependências, permitindo execução paralela na maior parte.

```
Semana 1 (paralelo):
  0.1 ──────────────────────────────► DONE
  0.3 ──────────────────────────────► DONE
  0.4 ──────────────────────────────► DONE
  0.5 ──────────────────────────────► DONE
  0.6 ──────────────────────────────► DONE  (depende de tokens definidos em 0.4 para refinamento)
  0.7 ──────────────────────────────► DONE

Semana 1 (bloqueada por 0.1):
  0.2 ─── aguarda 0.1 ────────────► DONE
```

**Caminho crítico:** `0.1 → 0.2`

As demais stories (0.3, 0.4, 0.5, 0.6, 0.7) podem ser executadas em qualquer ordem ou em paralelo.

### Ordem sugerida se executando sequencialmente (um executor)

1. **0.1** — Fixtures (base para validar 0.2)
2. **0.3** — Contrato Clone↔Wrapper (decisão mais complexa, M)
3. **0.4** — Temperatura (insumo para 0.6)
4. **0.5** — LGPD (impacto em toda a arquitetura)
5. **0.6** — Orçamento (usa tokens de 0.4)
6. **0.7** — Plágio (decisão pedagógica, pode precisar de input do PA)
7. **0.2** — ADR-001 + correção de bug (após fixtures de 0.1)

---

## Critério de Conclusão do Sprint 0

O Sprint 0 está completo quando:

- [ ] Todos os 7 stories têm status `Done`
- [ ] `docs/decisions/` contém os 6 ADRs (ADR-001 a ADR-006)
- [ ] `docs/fixtures/` contém as fixtures anonimizadas
- [ ] O bug em `squads/bacharelado-correcoes/tasks/exportar-planilha.md` foi corrigido
- [ ] Todos os ADRs foram revisados e aprovados por pelo menos 1 stakeholder
- [ ] @po (Pax) validou as stories antes da transição para Sprint 1

---

## Artefatos Gerados ao Final do Sprint 0

```
docs/
├── decisions/
│   ├── ADR-001-formato-ra.md
│   ├── ADR-002-clone-contract.md
│   ├── ADR-003-temperature-policy.md
│   ├── ADR-004-lgpd-retention.md
│   ├── ADR-005-budget-policy.md
│   └── ADR-006-plagio-policy.md
├── fixtures/
│   ├── README.md
│   ├── aba1-exemplo-anon.xlsx
│   └── batch-exemplo/
│       ├── aluno-a-entrega.pdf
│       ├── aluno-b-apresentacao.pptx
│       └── aluno-c-relatorio.docx
└── stories/
    ├── SPRINT-0-INDEX.md  (este arquivo)
    ├── 0.1.story.md
    ├── 0.2.story.md
    ├── 0.3.story.md
    ├── 0.4.story.md
    ├── 0.5.story.md
    ├── 0.6.story.md
    └── 0.7.story.md

squads/bacharelado-correcoes/tasks/
└── exportar-planilha.md  (corrigido — bug do padStart)
```

---

## Pré-requisitos para Sprint 1

Antes de iniciar o Sprint 1, os seguintes itens devem estar disponíveis:

| Item | Fonte | Obrigatório |
|------|-------|-------------|
| Regra de normalização de RA | ADR-001 | Sim |
| Função `normalize_ra()` documentada | ADR-001 | Sim |
| Schema JSON da resposta da IA | ADR-002 | Sim |
| Seções do SKILL.md para system prompt | ADR-002 | Sim |
| Parâmetros de temperature por fase | ADR-003 | Sim |
| max_tokens por fase | ADR-003 | Sim |
| Texto do banner de consentimento | ADR-004 | Sim |
| Regras de sanitização de logs | ADR-004 | Sim |
| Fórmula de estimativa de custo | ADR-005 | Sim |
| Hard limit padrão (BRL) | ADR-005 | Sim |
| Threshold de similaridade para plágio | ADR-006 | Sim |
| Fixtures de validação | Story 0.1 | Sim |

---

_Sprint 0 Index gerado por @sm (River) em 2026-05-22_
