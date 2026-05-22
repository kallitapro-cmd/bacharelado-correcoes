# Sprint 1 — Fundação técnica: Índice de Stories

**Projeto:** Corretor Acadêmico
**Sprint:** 1
**Objetivo do Sprint:** Construir toda a fundação técnica do sistema — setup do repositório, autenticação, deploy, conversores de arquivos, schemas Pydantic, leitor de planilha, logger seguro e audit log. Ao final do Sprint 1, a aplicação deve ser deployável no Streamlit Cloud com autenticação funcional e todos os conversores testados contra as fixtures reais.
**Status:** Planejado
**Criado em:** 2026-05-22
**Criado por:** @sm (River)
**Pré-requisito:** Sprint 0 completo (7 stories Done, ADR-001 a ADR-006 aprovados)

---

## Stories do Sprint

| ID | Título | Complexidade | Status | Dependências | Arquivos Principais |
|----|--------|-------------|--------|--------------|---------------------|
| [1.1](./1.1.story.md) | Setup inicial do repositório Python/Streamlit | S | Ready | Sprint 0 completo | `requirements.txt`, `app.py`, `src/` |
| [1.2](./1.2.story.md) | Autenticação com streamlit-authenticator + audit trail | M | Ready | 1.1 | `src/auth/authenticator.py`, `config.yaml.example` |
| [1.3](./1.3.story.md) | Configurar e validar deploy no Streamlit Cloud | S | Ready | 1.1, 1.2 | `docs/guides/deploy.md`, `.streamlit/secrets.toml.example` |
| [1.4](./1.4.story.md) | Validar conectividade e modelos da API Anthropic | S | Ready | 1.1 | `src/utils/api_client.py` |
| [1.5](./1.5.story.md) | Conversor PDF → texto (PyMuPDF + fallback OCR) | M | Ready | 1.1 | `src/converters/pdf_converter.py` |
| [1.6](./1.6.story.md) | Conversor PPTX → texto (python-pptx + fallback OCR) | M | Ready | 1.1 | `src/converters/pptx_converter.py` |
| [1.7](./1.7.story.md) | Conversor DOCX → texto (python-docx) | S | Ready | 1.1 | `src/converters/docx_converter.py` |
| [1.8](./1.8.story.md) | Conversor de imagem → texto (Pillow + Tesseract) | S | Ready | 1.1 | `src/converters/image_converter.py` |
| [1.9](./1.9.story.md) | Schemas Pydantic para todo o pipeline de dados | M | Ready | 1.1, ADR-002 | `src/models/schemas.py` |
| [1.10](./1.10.story.md) | Leitor da Aba 1 + normalizador de RA | M | Ready | 1.1, 1.9, ADR-001 | `src/matching/ra_normalizer.py`, `src/excel/excel_reader.py` |
| [1.11](./1.11.story.md) | Logger com filtro de secrets (safe_logger) | S | Ready | 1.1, ADR-004 | `src/utils/logger.py` |
| [1.12](./1.12.story.md) | Audit log de sessão com download CSV | S | Ready | 1.1, 1.2, ADR-004 | `src/utils/audit_log.py` |

**Complexidade total:** 5×S + 4×M = ~9 pontos (estimativa por T-shirt sizing)

---

## Mapa de Dependências

```
Sprint 0 (Done)
    │
    ▼
  1.1 (Setup) ─────────────────────────────────────────────────┐
    │                                                            │
    ├──► 1.2 (Auth) ──► 1.3 (Deploy)                           │
    │                                                            │
    ├──► 1.4 (API Client)                                       │
    │                                                            │
    ├──► 1.5 (PDF Converter)                                    │
    │                                                            │
    ├──► 1.6 (PPTX Converter)                                   │
    │                                                            │
    ├──► 1.7 (DOCX Converter)                                   │
    │                                                            │
    ├──► 1.8 (Image Converter)                                  │
    │                                                            │
    ├──► 1.9 (Schemas Pydantic) ──► 1.10 (Excel Reader + RA)   │
    │                                                            │
    ├──► 1.11 (Safe Logger)                                     │
    │                                                            │
    └──► 1.2 ──► 1.12 (Audit Log) ◄──────────────────────────────┘
```

---

## Caminho Crítico

```
1.1 → 1.9 → 1.10
```

Explicação: A Story 1.1 (setup) é o gate de entrada de todas as demais. A Story 1.9 (schemas) é um pré-requisito de 1.10 (excel reader + normalização de RA). O Excel reader é o ponto de integração entre a planilha do PA e o pipeline de batch do Sprint 2.

---

## Sequência Recomendada de Execução

### Sequencial (um executor)

Ordem ótima para minimizar bloqueios e validar dependências rapidamente:

1. **1.1** — Setup (desbloqueia todas as demais)
2. **1.9** — Schemas (desbloqueia 1.10; sem dependências além de 1.1)
3. **1.11** — Safe Logger (S, independente após 1.1 — crítico para ADR-004)
4. **1.2** — Auth (M, desbloqueia 1.3 e 1.12)
5. **1.10** — Excel Reader + RA (M, depende de 1.9 — caminho crítico)
6. **1.5** — PDF Converter (M, independente após 1.1)
7. **1.6** — PPTX Converter (M, independente após 1.1)
8. **1.4** — API Client (S, independente após 1.1)
9. **1.7** — DOCX Converter (S, independente após 1.1)
10. **1.8** — Image Converter (S, independente após 1.1)
11. **1.12** — Audit Log (S, depende de 1.2 — pode fazer depois de 1.2)
12. **1.3** — Deploy (S, depende de 1.1 + 1.2 — última pois valida tudo)

### Paralelo (múltiplos executores)

**Wave 1 (gate):**
- 1.1 (solo — desbloqueia tudo)

**Wave 2 (paralelo, após 1.1):**
- 1.9 (schemas — desbloqueia 1.10)
- 1.11 (safe logger)
- 1.2 (auth — desbloqueia 1.3 e 1.12)
- 1.4 (API client)
- 1.5 (PDF converter)
- 1.6 (PPTX converter)
- 1.7 (DOCX converter)
- 1.8 (image converter)

**Wave 3 (após Wave 2):**
- 1.10 (depende de 1.9)
- 1.12 (depende de 1.2)
- 1.3 (depende de 1.1 + 1.2)

---

## Critério de Conclusão do Sprint 1

O Sprint 1 está completo quando:

- [ ] Todos os 12 stories têm status `Done`
- [ ] `streamlit run app.py` funciona localmente com autenticação e layout básico
- [ ] Todos os 4 conversores passam nos testes unitários com as fixtures de `docs/fixtures/batch-exemplo/`
- [ ] `normalize_ra()` passa nos 8 casos de teste do ADR-001
- [ ] Schemas Pydantic são consistentes com ADR-002
- [ ] Safe logger não vaza RA nem API key nos testes
- [ ] App inicializa no Streamlit Cloud sem erros de startup

---

## Artefatos Gerados ao Final do Sprint 1

```
bacharelado-correcoes/
├── app.py                              (esqueleto funcional com auth)
├── requirements.txt                    (deps pinadas)
├── packages.txt                        (deps de sistema Streamlit Cloud)
├── .gitignore                          (cobrindo arquivos sensíveis)
├── config.yaml.example                 (estrutura sem senha real)
├── .streamlit/
│   ├── config.toml                     (tema básico)
│   └── secrets.toml.example            (variáveis de ambiente)
├── src/
│   ├── auth/
│   │   └── authenticator.py            (Story 1.2)
│   ├── converters/
│   │   ├── pdf_converter.py            (Story 1.5)
│   │   ├── pptx_converter.py           (Story 1.6)
│   │   ├── docx_converter.py           (Story 1.7)
│   │   └── image_converter.py          (Story 1.8)
│   ├── matching/
│   │   └── ra_normalizer.py            (Story 1.10)
│   ├── excel/
│   │   └── excel_reader.py             (Story 1.10)
│   ├── models/
│   │   └── schemas.py                  (Story 1.9)
│   └── utils/
│       ├── api_client.py               (Story 1.4)
│       ├── logger.py                   (Story 1.11)
│       └── audit_log.py               (Story 1.12)
├── tests/
│   └── unit/
│       ├── test_pdf_converter.py
│       ├── test_pptx_converter.py
│       ├── test_docx_converter.py
│       ├── test_image_converter.py
│       ├── test_schemas.py
│       ├── test_ra_normalizer.py
│       ├── test_excel_reader.py
│       ├── test_logger.py
│       ├── test_audit_log.py
│       └── test_api_client.py
└── docs/
    └── guides/
        └── deploy.md                   (Story 1.3)
```

---

## Referências Cruzadas com ADRs do Sprint 0

| ADR | Stories que implementam |
|-----|------------------------|
| ADR-001 — Normalização de RA | 1.10 (normalize_ra + excel_reader) |
| ADR-002 — Contrato Clone↔Wrapper | 1.9 (schemas FichaCorrecao, RespostaBatch) |
| ADR-003 — Temperature Policy | 1.4 (api_client: temperature=0, max_tokens=4096) |
| ADR-004 — LGPD e Retenção Zero | 1.2 (banner), 1.11 (safe_logger), 1.12 (audit log) |
| ADR-005 — Budget Policy | 1.3 (MAX_COST_BRL em secrets.toml) |
| ADR-006 — Política de Plágio | Nenhuma no Sprint 1 (implementado no Sprint 2+) |

---

## Pré-requisitos para Sprint 2

Ao concluir o Sprint 1, os seguintes itens estarão disponíveis para o Sprint 2 (pipeline de batch):

| Item | Story Fonte | Para usar em |
|------|-------------|-------------|
| `src/utils/api_client.py` | 1.4 | Wrapper de batch (Sprint 2) |
| `src/converters/*.py` | 1.5–1.8 | Upload e extração de texto |
| `src/models/schemas.py` | 1.9 | Validação de resposta da IA |
| `src/matching/ra_normalizer.py` | 1.10 | Matching entrega↔aluno |
| `src/excel/excel_reader.py` | 1.10 | Carregamento do manifesto |
| `src/utils/logger.py` | 1.11 | Todo logging da aplicação |
| `src/utils/audit_log.py` | 1.12 | Rastreamento de ações do PA |
| Autenticação funcional | 1.2 | Proteção do pipeline de batch |

---

_Sprint 1 Index gerado por @sm (River) em 2026-05-22_
