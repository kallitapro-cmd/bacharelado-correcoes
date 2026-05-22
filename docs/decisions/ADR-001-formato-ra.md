# ADR-001 — Formato Canônico de RA

**Data:** 2026-05-22
**Status:** Aceito
**Deciders:** @architect (Aria), PA confirmou com dados reais (turma de 124 alunos)
**Story:** [0.2](../stories/0.2.story.md)
**Fixture de referência:** [`docs/fixtures/aba1-exemplo-anon.xlsx`](../fixtures/aba1-exemplo-anon.xlsx)

---

## Contexto

O sistema acadêmico do Bacharelado em Administração utiliza **Registro Acadêmico (RA)** como chave primária para identificar alunos em planilhas, relatórios e processos de matching entre entregas e notas. A análise da turma real (124 alunos, semestres 2025/2026) revelou que o RA aparece em três formatos distintos na planilha do Professor Assistente (PA):

| Formato | Quantidade na turma real | Exemplo |
|---------|--------------------------|---------|
| 11 dígitos (canônico) | 111 alunos | `20260100418` |
| 10 dígitos (legado) | 13 alunos | `2026100418` |
| Especial (`0000xxxxxx`) | 1 aluno | `0000100041` |

O squad original (`squads/bacharelado-correcoes/tasks/exportar-planilha.md`) documentava a normalização com um exemplo **incorreto**, baseado em `padStart(11, '0')` aplicado de forma ambígua — produzindo `"20261004180"` (zero ao final) em vez do canônico `"20260100418"` (zero inserido na posição 4, após o ano).

Esse erro silencioso geraria **RAs inválidos** durante o matching, causando perda de notas, atribuições incorretas e impossibilidade de auditoria. Como a Story 0.1 entregou fixtures com RAs reais anonimizados cobrindo todos os três formatos, é possível formalizar a regra correta e validar antes de qualquer linha de código de produção (Sprint 1) ser escrita.

---

## Problema

### Bug específico (squad)

O arquivo `squads/bacharelado-correcoes/tasks/exportar-planilha.md` (linhas 24, 28–34) documenta:

```yaml
ra_normalization:
  rule: "Todo RA deve ter 11 dígitos"
  method: "padStart(11, '0')"
  examples:
    - input: "2026100418"
      output: "20261004180"   # ERRADO — padding aplicado à direita
```

Esse exemplo produz `"20261004180"` (11 caracteres, sim, mas com o zero **no final**), gerando um RA que **não existe** no sistema acadêmico. O método `padStart` em JavaScript adicionaria o zero **à esquerda** (resultando em `"02026100418"`), o que também é inválido. Em Python, `"2026100418".zfill(11)` produz o mesmo resultado errado (`"02026100418"`).

### Os três casos de RA na turma real

1. **RA canônico (11 dígitos):** já está no formato final. Estrutura: `AAAA0NNNNNN`, onde `AAAA` é o ano e o `0` na posição 4 é o separador entre ano e número sequencial. Exemplo: `20260100418` = ano `2026`, separador `0`, sequencial `100418`.

2. **RA legado (10 dígitos, anos 2025/2026):** o sistema legado omitiu o `0` separador. Estrutura: `AAAANNNNNN`. Exemplo: `2026100418` é o mesmo aluno que `20260100418`, mas sem o separador. Para canonicalizar, é necessário **inserir o `0` na posição 4** (após o ano), **NÃO** adicionar à esquerda ou à direita.

3. **RA especial (`0000xxxxxx`):** alunos cadastrados via processo manual (ex.: transferência, regime especial). Não seguem o padrão e devem ser tratados pela **Camada 3** do matching (revisão manual pelo PA), sem tentativa de normalização automática.

### Por que `zfill(11)` está errado

```python
"2026100418".zfill(11)   # → "02026100418"  ❌ INVÁLIDO
```

`zfill` adiciona zeros à esquerda. O resultado `"02026100418"` representa um RA que aparenta ser do ano `0202` (inexistente), descartando a semântica do ano `2026`. Esse erro quebraria o matching, a rastreabilidade por ano e a auditoria por semestre.

### Por que `ljust(11, '0')` ou `padStart` à direita também está errado

```python
"2026100418".ljust(11, '0')   # → "20261004180"  ❌ INVÁLIDO
```

Esse resultado deturpa o número sequencial do aluno, transformando `100418` em `1004180`, gerando um RA que não corresponde a nenhum aluno cadastrado.

---

## Decisão

### Regra formal

Para canonicalizar um RA para o formato de 11 dígitos:

1. **Strip:** remover espaços em branco ao redor.
2. **Bypass para 11 dígitos:** se o RA já tem 11 dígitos, retornar como está.
3. **Normalização para 10 dígitos com prefixo conhecido:** se o RA tem exatamente 10 dígitos **e** começa com `2025` ou `2026`, inserir o caractere `0` **na posição 4** (após o ano).
4. **Fallback (Camada 3):** qualquer outro formato (incluindo `0000xxxxxx`, strings vazias, formatos desconhecidos) deve ser retornado **sem alteração**, indicando ao chamador que esse RA exige revisão manual.

### Função canônica

```python
def normalize_ra(ra: str) -> str:
    """
    Normaliza um Registro Acadêmico (RA) para o formato canônico de 11 dígitos.

    Regra (ADR-001):
    - 11 dígitos          → retorna como está
    - 10 dígitos + 2025/  → insere '0' na posição 4 (após o ano)
      2026 prefix
    - Outros formatos     → retorna como está (Camada 3 — revisão manual)

    Args:
        ra: RA bruto, possivelmente com espaços ao redor.

    Returns:
        RA canônico de 11 dígitos quando aplicável, ou o RA original
        para casos especiais (a serem tratados pela Camada 3 do matching).
    """
    ra = str(ra).strip()
    if len(ra) == 10 and (ra.startswith('2026') or ra.startswith('2025')):
        return ra[:4] + '0' + ra[4:]
    return ra
```

### Contrato (invariantes)

- **Idempotência:** `normalize_ra(normalize_ra(x)) == normalize_ra(x)` para todo `x`.
- **Pureza:** sem efeitos colaterais, sem I/O, sem dependências externas.
- **Determinismo:** mesma entrada sempre produz mesma saída.
- **Preservação semântica:** o ano (`2025`/`2026`) e o sequencial do aluno são preservados após a normalização.

---

## Casos de Teste

Validados contra a fixture `docs/fixtures/aba1-exemplo-anon.xlsx` (8 RAs sintéticos cobrindo todos os caminhos).

| # | Entrada | Saída esperada | Regra aplicada | Rationale |
|---|---------|----------------|----------------|-----------|
| 1 | `"2026100418"` | `"20260100418"` | Inserção de `0` na posição 4 | RA de 10 dígitos, ano 2026 → adicionar separador. Caso mais comum do bug detectado. |
| 2 | `"2025100333"` | `"20250100333"` | Inserção de `0` na posição 4 | RA de 10 dígitos, ano 2025 → mesma regra. Confirma que `startswith('2025')` é reconhecido. |
| 3 | `"20260100418"` | `"20260100418"` | Bypass (já 11 dígitos) | Idempotência: RA canônico não é modificado. |
| 4 | `"0000100041"` | `"0000100041"` | Fallback (Camada 3) | Caso especial: não começa com `2025`/`2026`, então passa para revisão manual sem alteração. |
| 5 | `" 2026100418 "` | `"20260100418"` | `strip()` + inserção | Robustez a espaços ao redor (comum em planilhas com cópia/cola). |
| 6 | `"20260100418 "` | `"20260100418"` | `strip()` + bypass | Strip aplicado antes da verificação de comprimento — caso 11 dígitos com espaço final. |
| 7 | `""` | `""` | Fallback | Entrada vazia: retorna como está, sinalizando à Camada 3. |
| 8 | `"2024100500"` | `"2024100500"` | Fallback (ano desconhecido) | RA de 10 dígitos mas ano fora de 2025/2026 → não tenta normalizar. Conservador. |

### Validação cruzada com fixture

A fixture `docs/fixtures/aba1-exemplo-anon.xlsx` contém:

- **5 RAs de 11 dígitos** → todos devem passar pelo bypass (caso #3).
- **2 RAs de 10 dígitos** (prefixo `2026`) → ambos devem ser normalizados (caso #1).
- **1 RA especial** `0000100041` → fallback (caso #4).

Total: 8 RAs cobrindo 3 dos 4 caminhos principais. Os casos #5–#8 cobrem robustez (espaços, vazio, ano não suportado).

---

## Consequências

### O que muda

- O squad `squads/bacharelado-correcoes/tasks/exportar-planilha.md` recebe **correção do bloco `ra_normalization`** para refletir a regra canônica deste ADR (insert na posição 4, exemplo correto, contraindicação explícita a `zfill`/`padStart`).
- Toda implementação futura (Sprint 1 em diante) que precise normalizar RA **DEVE** usar a função `normalize_ra` definida acima como referência canônica.
- O matching aluno-entrega passa a operar em **três camadas explícitas:**
  - **Camada 1:** match direto por RA canônico (após normalização).
  - **Camada 2:** match por nome (quando RA está ausente ou ambíguo).
  - **Camada 3:** revisão manual (RAs especiais e fallbacks).

### O que não muda

- A estrutura da planilha do PA (3 abas, layout matricial da Aba 2) permanece inalterada.
- Os fixtures da Story 0.1 não precisam ser regerados — eles já refletem a turma real.
- O squad de extração/parsing dos demais arquivos (`calibrar-batch.md`, `corrigir-batch.md`, `gerar-feedback.md`) não é afetado por esta decisão.

### Impacto em outros módulos

| Módulo | Impacto | Quando |
|--------|---------|--------|
| Parser da Aba 1 do PA (Sprint 1) | DEVE aplicar `normalize_ra()` em toda leitura de RA | Story 1.x |
| Matching entrega ↔ aluno (Sprint 1) | DEVE chamar `normalize_ra()` antes do lookup | Story 1.x |
| Exportação para planilha (Sprint 2+) | DEVE garantir que todos os RAs de saída estão canônicos | Story 2.x |
| Auditoria/relatórios (Sprint 2+) | DEVE referenciar este ADR para validação de formatos | Story 2.x |

### Riscos mitigados

- **Perda silenciosa de notas:** sem este ADR, um aluno com RA legado (10 dígitos) seria normalizado para um RA inexistente (`20261004180` ou `02026100418`) e suas notas seriam atribuídas a "ninguém".
- **Inconsistência entre módulos:** ao centralizar a regra em ADR e função única, evita-se que diferentes partes do sistema implementem normalizações divergentes.
- **Falsos positivos no matching:** o tratamento explícito do caso `0000xxxxxx` como fallback impede que esses alunos sejam silenciosamente atribuídos a outros registros.

### Custos aceitos

- A função não normaliza RAs de anos anteriores a 2025 nem posteriores a 2026. Quando novas turmas forem cadastradas, o ADR deve ser revisado e a função estendida (ex.: incluir `startswith('2027')`).
- Casos especiais (`0000xxxxxx`) **sempre** exigem intervenção manual do PA — o sistema não tenta adivinhar a identidade do aluno.

---

## Alternativas Consideradas

### 1. `zfill(11)` ou `padStart(11, '0')` — REJEITADO

Adiciona zeros à esquerda, produzindo `"02026100418"`. Quebra a semântica do ano.

### 2. `ljust(11, '0')` ou `padEnd(11, '0')` — REJEITADO

Adiciona zeros à direita, produzindo `"20261004180"`. Deturpa o sequencial do aluno.

### 3. Regex genérica `(\d{4})(\d{6})` → `\1 + '0' + \2` — REJEITADO

Funcional, mas menos explícito que a verificação de prefixo. Aceitaria RAs de qualquer ano (2020, 2030, etc.) sem validação semântica. A versão com `startswith` é mais conservadora e auditável.

### 4. Normalização agressiva (tentar matching por nome quando RA falha) — ADIADO

Decidimos manter a normalização **estrita** (apenas casos conhecidos) e delegar matching por nome para a Camada 2 do matching, em uma decisão separada (futuro ADR-002). Isso mantém o ADR-001 focado e auditável.

---

## Referências

- **Story 0.1** — Criação dos fixtures sintéticos: [`docs/stories/0.1.story.md`](../stories/0.1.story.md)
- **Story 0.2** — Esta decisão: [`docs/stories/0.2.story.md`](../stories/0.2.story.md)
- **Fixture validada** — [`docs/fixtures/aba1-exemplo-anon.xlsx`](../fixtures/aba1-exemplo-anon.xlsx) (8 RAs cobrindo todos os caminhos)
- **README dos fixtures** — [`docs/fixtures/README.md`](../fixtures/README.md) (distribuição da turma real)
- **Squad corrigido** — [`squads/bacharelado-correcoes/tasks/exportar-planilha.md`](../../squads/bacharelado-correcoes/tasks/exportar-planilha.md)
- **Arquitetura v2.0** — Decisão de adotar matching em 3 camadas

---

## Histórico

| Data | Autor | Mudança |
|------|-------|---------|
| 2026-05-22 | @dev (Dex) | Versão inicial — aceita. Validada contra fixture da Story 0.1 com 8 RAs reais anonimizados. |
