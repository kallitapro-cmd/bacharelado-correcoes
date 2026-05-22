# ADR-003 — Política de Temperature e Determinismo da API Anthropic

**Data:** 2026-05-22
**Status:** Aceito
**Deciders:** @architect (Aria)
**Stakeholders consultados:** PA (Professor Assistente), Tech Lead
**Stories relacionadas:** Story 0.4 (este ADR), Story 0.6 (ADR-005 — orçamento)

---

## Contexto

O sistema Corretor Acadêmico realiza correção automatizada de trabalhos com auxílio de IA (API Anthropic). O fluxo passa por quatro fases distintas, cada uma com requisitos próprios de reprodutibilidade, naturalidade e custo:

1. **Correção em batch** — gera nota e pontuação por critério para cada aluno
2. **Calibração** — revisa e ajusta o ranking de notas entre alunos do batch
3. **Geração de feedback (texto)** — produz o texto explicativo entregue ao aluno
4. **Regeneração individual** — refaz a correção de um único aluno quando o PA rejeita o resultado e solicita nova análise

A **reprodutibilidade das notas** é exigência inegociável do contexto acadêmico:

- O PA precisa demonstrar, em caso de contestação por aluno ou banca, que a mesma entrada (mesmo trabalho + mesmo critério) produz a mesma nota em execuções diferentes.
- Auditorias internas da instituição podem solicitar reexecução de batches antigos para validar metodologia.
- A regeneração solicitada pelo PA deve ser determinística: se o PA rejeita e pede novamente sem alterar o prompt, a saída deve ser estável (a regeneração existe para corrigir o **prompt/critério**, não para "rolar o dado").

Em tensão com esse requisito está a **naturalidade do feedback textual** entregue ao aluno. Feedbacks idênticos entre alunos com erros similares produzem percepção robótica e reduzem o valor pedagógico. Uma variação leve no texto — mantendo o conteúdo técnico — melhora a experiência sem comprometer a auditoria, porque o que é auditado é a **nota**, não o texto literal do feedback.

Esta decisão precisa ser formalizada por política, não resolvida ad-hoc no código, porque afeta:
- Conformidade com a Constitution do projeto (Article V — Quality First).
- Estimativa de custo (ADR-005) — `max_tokens` impacta diretamente o preço por chamada.
- Capacidade do PA defender notas em processos de revisão.

---

## Decisão

Adotar a seguinte política de temperature e parâmetros por fase:

- **Fases que afetam notas ou ranking (correção, calibração, regeneração):** `temperature = 0` — saída determinística.
- **Fase que produz apenas texto (feedback ao aluno):** `temperature = 0.3` — variação leve, sem afetar a nota já calculada.
- **`top_p`:** manter o padrão do modelo (não definir explicitamente). Com `temperature = 0`, a influência de `top_p` é desprezível; com `temperature = 0.3`, o padrão da API já fornece comportamento adequado para texto natural.
- **Modelo por fase:** seguir o que está definido na arquitetura v2.0 (Haiku para correção e calibração de notas — barato e suficiente; Sonnet apenas onde explicitamente justificado em ADR futuro).

Esta política se aplica a todas as chamadas à API Anthropic feitas pelo sistema. Qualquer desvio (ex: `temperature` diferente em uma chamada específica) exige novo ADR ou ADR de revisão deste documento.

---

## Tabela de Parâmetros por Fase

| Fase | Modelo | `temperature` | `max_tokens` | `top_p` | Justificativa |
|------|--------|---------------|--------------|---------|---------------|
| **Correção (batch)** | `claude-haiku-4-5-20251001` | `0` | `4096` | padrão | Reprodutibilidade obrigatória para auditoria acadêmica. A nota gerada aqui é o produto principal do sistema e precisa ser estável dado o mesmo prompt + mesma versão do modelo. |
| **Calibração** | `claude-sonnet-4-6` | `0` | `4096` | padrão | Ranking determinístico — mesma entrada (notas do batch) deve produzir o mesmo ranking sempre. Justifica o uso de Sonnet (mais caro) pelo volume menor (1 chamada por batch, não 1 por aluno) e pela necessidade de raciocínio comparativo entre alunos. |
| **Feedback (texto)** | `claude-haiku-4-5-20251001` | `0.3` | `4096` | padrão | Variação leve no texto evita feedbacks idênticos entre alunos com erros similares, melhorando percepção pedagógica. Não compromete a nota porque a nota é fixada antes desta fase (vinda da correção determinística). |
| **Regeneração individual** | `claude-haiku-4-5-20251001` | `0` | `4096` | padrão | Quando o PA rejeita uma correção e solicita nova análise, a expectativa é que a regeneração seja determinística sobre o prompt ajustado. Variação aleatória aqui mascara a causa raiz do problema (prompt mal calibrado) e impede o PA de aprender a ajustar critérios. |

> **Nota (2026-05-22):** `max_tokens` unificado em 4096 para todas as fases por decisão do PA. ADR-003 é fonte canônica para temperature; ADR-002 é fonte canônica para o schema de resposta. Conflito resolvido antes do Sprint 1.

---

## Implicação para Auditoria

Com `temperature = 0`, dado o mesmo prompt + a mesma versão do modelo + o mesmo trabalho do aluno, a API Anthropic produz saída **idêntica ou quase idêntica** (a tokenização e o sampling determinístico garantem isso na maioria absoluta dos casos).

Isso permite ao PA, em caso de contestação:

1. Reexecutar a correção do trabalho contestado.
2. Comparar a saída com o registro original do batch.
3. Demonstrar que o critério aplicado foi o mesmo, ignorando aleatoriedade do modelo.

**Caveat técnico:** A API Anthropic não garante 100% de determinismo absoluto (variações marginais podem ocorrer em <1% dos casos devido a otimizações internas). Para defesa em auditoria, o que se demonstra é:
- O prompt usado é o mesmo (logado).
- A versão do modelo é a mesma (logada via `model` no response).
- A política de `temperature = 0` foi aplicada (logada via parâmetros do request).

Esses três pontos são suficientes para demonstrar reprodutibilidade metodológica, mesmo que a saída literal tenha variações marginais.

**Sobre o feedback (temperature = 0.3):** O texto do feedback pode variar entre execuções, e isso é intencional. A nota — que é o objeto auditável — é determinística e vem da fase de correção, não da fase de feedback. O texto é uma camada de comunicação, não de avaliação. Em caso de contestação, o que vale juridicamente é a nota + critério, não a redação do feedback.

---

## Implicação para Custo

`max_tokens` é o teto de tokens de saída por chamada. Mais tokens = mais caro, mesmo que o modelo não use todos. Os valores foram dimensionados pelo conteúdo mínimo viável de cada fase:

| Fase | `max_tokens` | Justificativa do dimensionamento |
|------|--------------|----------------------------------|
| Correção | `4096` | Teto unificado por decisão PA (2026-05-22). Suficiente para: nota global + pontuação por 5-7 critérios + breve justificativa por critério em JSON estruturado. Output típico real é menor; este é o teto conservador. |
| Calibração | `4096` | Teto unificado por decisão PA (2026-05-22). Suficiente para: ranking ajustado de até 120 alunos em formato compacto + nota de calibração agregada. |
| Feedback | `4096` | Teto unificado por decisão PA (2026-05-22). Para 2-4 parágrafos de feedback textual ao aluno, o consumo real é uma fração deste teto. |
| Regeneração | `4096` | Teto unificado por decisão PA (2026-05-22). Mesmo dimensionamento da correção, pois o output esperado é o mesmo. |

**Impacto no orçamento (referência cruzada ADR-005):**

A combinação `modelo × max_tokens × N_chamadas_por_batch` define o custo do batch. Para um batch de 120 alunos com os valores acima (worst-case, todas as fases batendo no teto de 4096 tokens — improvável na prática):

- **Correção (Haiku):** 120 chamadas × até 4096 tokens output × $4.00/1M = até $1.97 (saída)
- **Calibração (Sonnet):** 1 chamada × até 4096 tokens output × $15.00/1M = até $0.061 (saída)
- **Feedback (Haiku):** 120 chamadas × até 4096 tokens output × $4.00/1M = até $1.97 (saída)
- **Total output worst-case (sem input):** ~$4.00

> Os preços de Haiku e Sonnet acima refletem o ADR-005 (verificado no Anthropic Console em 2026-05-22). Este worst-case representa o teto absoluto se 100% das chamadas usarem 100% do `max_tokens` — o ADR-005 documenta a estimativa realista baseada no consumo médio esperado.

O ADR-005 detalha o cálculo completo incluindo tokens de input, taxa de câmbio para BRL e o hard limit operacional.

**Importante:** Reduzir `max_tokens` é a alavanca primária de redução de custo. Aumentá-los exige nova justificativa em ADR de revisão.

---

## `max_tokens` Recomendados por Fase (Resumo)

| Fase | `max_tokens` | Tamanho típico esperado |
|------|--------------|-------------------------|
| Correção | **4096** | JSON com nota + critérios + justificativas |
| Calibração | **4096** | JSON com ranking + ajustes |
| Feedback | **4096** | 2-4 parágrafos de texto natural |
| Regeneração | **4096** | Mesmo formato da correção |

Esses são os valores oficiais a serem implementados no Sprint 1. O teto unificado em 4096 (decisão PA, 2026-05-22) substitui os valores anteriores por fase — o consumo real continua proporcional ao tamanho típico esperado de cada output.

---

## Consequências

**Positivas:**

1. **Auditoria viável** — PA pode defender notas com base em reprodutibilidade documentada.
2. **Custo previsível** — `max_tokens` fixos permitem estimativa precisa de custo no ADR-005.
3. **Política única** — implementação no Sprint 1 não precisa de decisão por chamada; basta consultar esta tabela.
4. **Feedback natural** — alunos não recebem textos idênticos entre si, preservando valor pedagógico.

**Negativas / Trade-offs aceitos:**

1. **Feedback não reprodutível literalmente** — se um aluno questionar "por que o feedback do colega é diferente do meu se erramos o mesmo conceito", a resposta é "o sistema usa variação intencional no texto, mas o critério e a nota são idênticos". Aceito porque a auditabilidade que importa é da nota.
2. **Sonnet na calibração é mais caro que Haiku** — aceito porque calibração ocorre 1 vez por batch (não 1 por aluno), e o ganho de qualidade no ranking comparativo justifica o custo marginal.
3. **`top_p` no padrão** — escolha conservadora; se em produção observarmos comportamento subótimo, esta decisão pode ser revisada via novo ADR.

**Impacto direto em outros ADRs:**

- **ADR-005 (Orçamento):** as estimativas de custo DEVEM usar os `max_tokens` definidos aqui como teto. Se ADR-005 quiser usar valores diferentes, deve atualizar ADR-003 primeiro.
- **ADR-002 (Contrato Clone↔Wrapper):** o schema de resposta da IA deve caber dentro dos `max_tokens` definidos. Se o schema crescer, este ADR precisa ser revisado.

**Implementação no Sprint 1:**

O wrapper Python que chama a API Anthropic deve expor a configuração de temperature e max_tokens por fase como constantes nomeadas (não literais espalhados no código), facilitando auditoria do código e futura mudança de política.

---

## Referências

- **ADR-002** — Contrato Clone↔Wrapper (schema da resposta da IA)
- **ADR-005** — Orçamento e Hard Limit por Batch (cálculo de custo usando os `max_tokens` deste ADR)
- **Anthropic API Docs** — [Messages API parameters](https://docs.anthropic.com/en/api/messages) (referência para `temperature`, `max_tokens`, `top_p`)
- **Constitution AIOX** — Article V (Quality First) — exigência de reprodutibilidade documentada
- **Story 0.4** — `docs/stories/0.4.story.md` (story que gerou este ADR)
- **Story 0.6** — `docs/stories/0.6.story.md` (story do ADR-005, consumidor desta política)

---

## Histórico de Revisões

| Data | Autor | Mudança |
|------|-------|---------|
| 2026-05-22 | @architect (Aria) | Criação inicial — Story 0.4 |
| 2026-05-22 | PA | max_tokens unificado em 4096 — conflito ADR-002 vs ADR-003 resolvido |
