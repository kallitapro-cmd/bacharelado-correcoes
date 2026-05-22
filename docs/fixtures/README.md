# Fixtures — Corretor Acadêmico

Este diretório contém **fixtures sintéticas** (dados fictícios) utilizadas para validar a arquitetura de correção automática do Bacharelado em Administração e servir como base para testes do Sprint 1.

> **IMPORTANTE: Dados Sintéticos**
>
> Todos os arquivos neste diretório são **completamente anonimizados e sintéticos**.
>
> - Nenhum nome real de aluno está presente
> - Todos os RAs são fictícios, mas seguem o **padrão estrutural real** do sistema acadêmico
> - Nenhum dado pessoal (e-mail, telefone) é real — todos seguem padrão `aluno.<letra>@exemplo.edu.br` e `(11) 99999-XXXX`
> - O conteúdo dos arquivos de entrega (PDF/PPTX/DOCX) é texto acadêmico genérico

---

## Estrutura

```
docs/fixtures/
├── README.md                          # Este arquivo
├── generate_fixtures.py               # Script que regera todos os fixtures
├── aba1-exemplo-anon.xlsx             # Planilha do PA (3 abas)
└── batch-exemplo/                     # Batch de entregas dos alunos
    ├── aluno-a-entrega.pdf            # PDF de exemplo
    ├── aluno-b-apresentacao.pptx      # PPTX de exemplo
    └── aluno-c-relatorio.docx         # DOCX de exemplo
```

---

## Padrão de RAs

O sistema acadêmico do bacharelado utiliza dois formatos legados de RA. O matching e a normalização estão formalizados no **ADR-001** (Story 0.2).

| Quantidade na turma real | Formato | Padrão | Exemplo |
|--------------------------|---------|--------|---------|
| 111 alunos | **11 dígitos** (canônico) | `2026010XXXX` ou `2025010XXXX` | `20260100418` |
| 13 alunos | **10 dígitos** (legado) | `2026100XXX` (zero faltante na posição 4) | `2026100418` |
| 1 aluno | **caso especial** | `0000100041` (matching manual / Camada 3) | `0000100041` |

### Regra de normalização (ADR-001)

- RAs de **10 dígitos** começando com `2025` ou `2026` → **inserir `0` na posição 4** (após o ano).
  - Exemplo: `2026100418` → `20260100418`
- **NÃO usar `zfill(11)`** — isso adicionaria zero à esquerda, gerando um RA inválido (`02026100418`).
- RAs especiais (ex. `0000100041`) → fallback para revisão manual (Camada 3 do matching).

### Distribuição nos fixtures

A fixture `aba1-exemplo-anon.xlsx` (aba `Alunos`) contém 8 RAs sintéticos representando o mix real:

- **5 RAs de 11 dígitos** (padrão `2026010XXXX`)
- **2 RAs de 10 dígitos** (padrão `2026100XXX`)
- **1 RA especial** (`0000100041`)

Esses 8 RAs cobrem todos os caminhos de normalização e fallback que a Story 0.2 (ADR-001) precisa testar.

---

## Estrutura da Planilha do PA

A planilha original do Professor Assistente possui **3 abas**, cada uma com layout diferente:

### Aba 1 — `Alunos` (Manifesto)

Lista canônica de alunos da turma.

| Coluna | Descrição |
|--------|-----------|
| RA | Registro Acadêmico (10 ou 11 dígitos) |
| Nome Completo | Nome do aluno |
| E-mail | Contato institucional |
| Telefone | Contato pessoal |

> Na turma real: 124 linhas. Na fixture: 8 linhas representativas.

### Aba 2 — `Consolidado` (Notas por Etapa)

Layout matricial complexo com cabeçalhos mesclados.

- **Linha 1:** datas das atividades **mescladas** por etapa (ex: célula `B1:D1` = `"27/04/2026"` cobrindo as 3 atividades dessa etapa).
- **Linha 2:** identificadores das atividades (`A1`, `A2`, `A3`).
- **Coluna A:** RA do aluno.
- **Linhas 3+:** notas de 0 a 10.

### Aba 3+ — `Pós-Work Etapa N` (Detalhe por Etapa)

Uma aba **por etapa**, com header de 2 linhas.

- **Linha 1:** data da etapa (ex: `27/04/2026`).
- **Linha 2:** rótulos das colunas (`RA`, `Nome`, `Nota A1`, `Nota A2`, `Comentário`, `Grupo`).
- **Linhas 3+:** 1 linha por aluno.

---

## Como usar nos testes (Sprint 1+)

```python
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "docs" / "fixtures"

# Planilha
spreadsheet = FIXTURES_DIR / "aba1-exemplo-anon.xlsx"

# Batch de entregas
batch_dir = FIXTURES_DIR / "batch-exemplo"
pdf_sample = batch_dir / "aluno-a-entrega.pdf"
pptx_sample = batch_dir / "aluno-b-apresentacao.pptx"
docx_sample = batch_dir / "aluno-c-relatorio.docx"
```

### Cenários cobertos

| Cenário | Fixture | Onde testar |
|---------|---------|-------------|
| Parsing de planilha multi-aba | `aba1-exemplo-anon.xlsx` | Story 1.x (parser do PA) |
| Normalização de RA 10→11 dígitos | linhas com RAs `2026100XXX` | Story 0.2 (ADR-001) |
| Matching manual (RA especial) | linha com `0000100041` | Story 0.2 (Camada 3) |
| Extração de texto PDF | `aluno-a-entrega.pdf` | Story 1.x (parser de entregas) |
| Extração de texto PPTX | `aluno-b-apresentacao.pptx` | Story 1.x (parser de entregas) |
| Extração de texto DOCX | `aluno-c-relatorio.docx` | Story 1.x (parser de entregas) |

---

## Regenerando os fixtures

Todos os arquivos podem ser regenerados deterministicamente com:

```bash
python3 docs/fixtures/generate_fixtures.py
```

Dependências (instaladas via `pip install --user`):

- `openpyxl` (>= 3.1) — geração do XLSX
- `reportlab` (>= 4.0) — geração do PDF
- `python-pptx` (>= 1.0) — geração do PPTX
- `python-docx` (>= 1.0) — geração do DOCX

O script é **idempotente**: pode ser executado várias vezes e gera saídas idênticas.

---

## Referências

- **ADR-001** (Story 0.2): normalização de RAs — `docs/decisions/ADR-001-*.md`
- **Story 0.1**: criação destes fixtures — `docs/stories/0.1.story.md`
- **Arquitetura v2.0**: estrutura confirmada da planilha do PA
