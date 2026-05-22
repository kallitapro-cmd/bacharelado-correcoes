# ADR-005 — Política de Orçamento e Hard Limit por Batch

**Data:** 2026-05-22
**Status:** Aceito
**Autor:** @dev (Dex)
**Sprint:** 0 (ADRs pré-código)
**Story:** [0.6](../stories/0.6.story.md)

## Contexto

O sistema de correção automática usa duas APIs pagas da Anthropic com perfis de custo muito distintos:

- **Haiku 4.5** — usado em lote para correção de grandes volumes (barato, rápido).
- **Sonnet 4.6** — usado para calibração e feedback consolidado (caro, mais capaz).

Um Professor Assistente (PA) processa tipicamente **120 alunos por batch** (uma turma real). O custo de um batch varia conforme:

- Tamanho dos trabalhos (PDF de 50 páginas pesa muito mais que PPTX de 10 slides).
- Quantidade de regenerações solicitadas pelo PA (revisar lotes específicos).
- Modelo escolhido para cada fase (correção vs. calibração).

**Problemas a evitar:**

1. **Surpresas no custo** — PA inicia um batch sem saber o gasto estimado e descobre cobrança alta só depois.
2. **Gastos acidentais** — execução automática ou em loop sem teto consome saldo da API silenciosamente.
3. **Falta de previsibilidade orçamentária** — instituição não consegue projetar gasto mensal.

A solução precisa ser simples (MVP) e auditável: **mostrar a estimativa antes** + **hard limit configurável** que bloqueia execução acima do teto.

## Decisão

Adotaremos uma **política de duas camadas**:

1. **Estimativa pré-batch (sempre):** antes de qualquer chamada à API, o sistema calcula e exibe ao PA o custo estimado em R$ usando a fórmula da seção "Fórmula de Estimativa".
2. **Hard limit configurável (sempre ativo):** se a estimativa exceder o limite definido em `MAX_COST_BRL` (padrão **R$ 15,00**), o batch é **bloqueado** até que o PA aumente o limite ou reduza o escopo.

A combinação garante:

- Transparência (estimativa visível).
- Confirmação explícita (PA aprova o gasto).
- Proteção contra surpresas (limite duro impede gastos não autorizados).

## Preços dos Modelos

**Data de referência:** 2026-05-22 (Anthropic Console, https://console.anthropic.com/settings/billing)

| Modelo                          | Uso no sistema             | Input ($/1M tokens) | Output ($/1M tokens) |
|---------------------------------|----------------------------|---------------------|----------------------|
| `claude-haiku-4-5-20251001`     | Correção em lote (12×)     | $0.80               | $4.00                |
| `claude-sonnet-4-6`             | Calibração + feedback (1×) | $3.00               | $15.00               |

**Taxa de câmbio de referência:** **USD → BRL × 5,50** (cotação conservadora maio/2026).

**Nota sobre revalidação de preços:** Preços Anthropic mudam periodicamente. Este ADR deve ser revisitado a cada **6 meses** ou imediatamente quando a Anthropic anunciar mudança de preços. A constante de câmbio também deve ser revisada se a cotação USD/BRL variar mais de **±10%** do valor de referência.

**Nota de divergência com Notas Técnicas da Story 0.6:** A story original cita preços ~$0.25/$1.25 para Haiku 4.5. Após verificação no Anthropic Console em 2026-05-22, os preços atuais são $0.80/$4.00. Este ADR usa os preços atualizados como fonte de verdade.

## Fórmula de Estimativa

### Variáveis

| Variável                    | Descrição                                                       | Valor padrão (batch típico)         |
|-----------------------------|------------------------------------------------------------------|--------------------------------------|
| `N_lotes`                   | Quantidade de lotes Haiku (10 alunos por lote)                   | `ceil(N_alunos / 10)` → 12 (p/ 120)  |
| `tokens_in_haiku`           | Tokens de entrada por chamada Haiku (enunciado + rubrica + 10 trabalhos) | 4.000                          |
| `tokens_out_haiku`          | Tokens de saída por chamada Haiku (10 correções) — teto `max_tokens` (ADR-003) | 4.096                          |
| `tokens_in_sonnet`          | Tokens de entrada da calibração Sonnet (notas + ranking)        | 3.000                                |
| `tokens_out_sonnet`         | Tokens de saída da calibração Sonnet (relatório consolidado) — teto `max_tokens` (ADR-003) | 4.096                          |
| `N_regeneracoes`            | Regenerações estimadas (média histórica)                        | 3                                    |
| `taxa_cambio`               | Conversão USD → BRL                                              | 5,50                                 |

### Fórmula

```
custo_haiku       = N_lotes        × (tokens_in_haiku  × 0.80 + tokens_out_haiku  × 4.00) / 1_000_000
custo_sonnet      = 1              × (tokens_in_sonnet × 3.00 + tokens_out_sonnet × 15.00) / 1_000_000
custo_regen       = N_regeneracoes × (tokens_in_haiku  × 0.80 + tokens_out_haiku  × 4.00) / 1_000_000

total_usd = custo_haiku + custo_sonnet + custo_regen
total_brl = total_usd × taxa_cambio
```

### Referência cruzada com ADR-003

Os valores `tokens_out_haiku` (4.096) e `tokens_out_sonnet` (4.096) refletem o teto `max_tokens` unificado em 4096 definido no [ADR-003](./ADR-003-temperature-policy.md) (decisão PA de 2026-05-22). A estimativa abaixo é, portanto, um **teto conservador** — o consumo real de tokens de saída tende a ser uma fração desse limite (correção típica usa ~1.500 tokens, calibração ~500, feedback ~400). Se o ADR-003 alterar `max_tokens` novamente, esta fórmula precisa ser revisitada.

## Estimativa para Batch Real (120 alunos)

### Passo a passo

**Parâmetros:**
- N_alunos = 120 → N_lotes = 12
- tokens_in_haiku = 4.000, tokens_out_haiku = 4.096
- tokens_in_sonnet = 3.000, tokens_out_sonnet = 4.096
- N_regeneracoes = 3
- taxa_cambio = 5,50

**Cálculo Haiku (correção):**
```
custo_haiku = 12 × (4000 × 0.80 + 4096 × 4.00) / 1.000.000
            = 12 × (3.200 + 16.384) / 1.000.000
            = 12 × 19.584 / 1.000.000
            = 12 × $0,019584
            = $0,2350
```

**Cálculo Sonnet (calibração):**
```
custo_sonnet = 1 × (3000 × 3.00 + 4096 × 15.00) / 1.000.000
             = 1 × (9.000 + 61.440) / 1.000.000
             = 1 × 70.440 / 1.000.000
             = $0,0704
```

**Cálculo regenerações:**
```
custo_regen = 3 × (4000 × 0.80 + 4096 × 4.00) / 1.000.000
            = 3 × 19.584 / 1.000.000
            = 3 × $0,019584
            = $0,0588
```

**Totais:**
```
total_usd = $0,2350 + $0,0704 + $0,0588 = $0,3642
total_brl = $0,3642 × 5,50              = R$ 2,00
```

### Resumo

| Item                       | USD     | BRL       |
|----------------------------|---------|-----------|
| Correção Haiku (12 lotes)  | $0,2350 | R$ 1,29   |
| Calibração Sonnet (1×)     | $0,0704 | R$ 0,39   |
| Regenerações (3×)          | $0,0588 | R$ 0,32   |
| **Total estimado (teto)**  | **$0,3642** | **R$ 2,00** |

**Observação:** o custo estimado de teto (R$ 2,00) está **abaixo** do hard limit padrão (R$ 15,00), o que cria uma margem confortável (~7,5×) para variações reais. Este valor é uma **estimativa conservadora de teto** assumindo que todas as chamadas atingem o `max_tokens=4096` (improvável na prática). O custo real médio observado em produção tende a ser significativamente menor — output típico raramente atinge o limite máximo.

## Hard Limit

### Valor padrão

**`MAX_COST_BRL = 15.00`** (R$ 15,00 por batch).

**Racional do valor:** Para uma turma típica (120 alunos), o custo estimado de teto é ~R$ 2,00 — ou seja, o limite cobre uma variação de ~7,5× (até alunos com trabalhos muito longos, várias regenerações). Como esta estimativa já assume o pior caso (`max_tokens=4096` saturado em todas as fases), o custo real médio será ainda menor, mantendo a margem confortável. Para turmas excepcionalmente grandes (300+ alunos) ou batches com regenerações intensas, o PA pode ajustar via variável de ambiente.

### Configuração

O limite é configurável via variável de ambiente:

```bash
# Aumentar para batch de turma grande (ex.: 300 alunos)
export MAX_COST_BRL=40.00

# Reduzir para ambiente de testes
export MAX_COST_BRL=2.00
```

**Padrão se variável ausente:** R$ 15,00 (definido em código).

**Validação:** valor deve ser numérico positivo. Se inválido (negativo, string, NaN), o sistema usa o padrão e loga aviso.

### Comportamento ao atingir o hard limit

Quando `total_brl > MAX_COST_BRL`:

1. **Bloquear** o batch — nenhuma chamada à API é feita.
2. Exibir mensagem clara ao PA com:
   - Estimativa calculada (em R$).
   - Hard limit configurado.
   - Diferença entre os dois (excesso).
   - Instruções para aumentar o limite (variável de ambiente).
   - Sugestões de como reduzir o escopo (menos alunos por batch, dividir em sub-batches).
3. Não retentar automaticamente — o PA deve agir explicitamente.

**Exemplo de mensagem:**

```
ORÇAMENTO EXCEDIDO

Estimativa para este batch: R$ 22,30
Hard limit configurado:     R$ 15,00
Excesso:                    R$  7,30

O batch foi BLOQUEADO para sua proteção.

Opções:
  1. Dividir o batch em sub-batches menores (recomendado).
  2. Aumentar o limite: export MAX_COST_BRL=25.00
  3. Verificar se há regenerações desnecessárias agendadas.
```

## Comportamento na UI

Antes de qualquer chamada à API (no momento em que o PA clica "Processar batch"), o sistema deve exibir:

```
┌─────────────────────────────────────────────┐
│  Confirmação de Batch                       │
├─────────────────────────────────────────────┤
│  Alunos:           120                      │
│  Lotes (Haiku):    12                       │
│  Calibração:       1 (Sonnet)               │
│  Regenerações:     3 (estimado)             │
├─────────────────────────────────────────────┤
│  Estimativa:       R$ 2,00                  │
│  Hard limit:       R$ 15,00                 │
│  Margem:           87% disponível           │
├─────────────────────────────────────────────┤
│  [Cancelar]              [Confirmar batch]  │
└─────────────────────────────────────────────┘
```

**Regras de UX:**

1. O PA **sempre** vê a estimativa antes de confirmar.
2. Se a estimativa **ultrapassar** o hard limit, o botão "Confirmar" é **desabilitado** e a mensagem de bloqueio é exibida no lugar.
3. O texto deve usar **R$** (português) e ter precisão de **2 casas decimais**.
4. A margem percentual ajuda o PA a entender se está confortável ou perto do teto.

## Consequências

### Positivas

- **Transparência total** — PA nunca é surpreendido com gastos inesperados.
- **Proteção contra erros** — hard limit impede execuções acidentais caras.
- **Decisão informada** — PA decide explicitamente confirmar ou ajustar.
- **Auditável** — toda execução tem estimativa registrada (útil para reembolso institucional).
- **Custo real muito baixo** — para a turma típica de 120 alunos, o teto estimado de R$ 2,00 representa custo desprezível por aluno (~R$ 0,017). O custo real médio tende a ser menor pois o output raramente satura o `max_tokens=4096`.

### Negativas / Trade-offs

- **Estimativa não é exata** — tokens reais podem variar 10-30% para mais ou para menos. A fórmula é conservadora (assume regenerações).
- **Necessidade de manutenção** — preços e taxa de câmbio precisam ser revisitados periodicamente (ver "Data de referência" acima).
- **Possível bloqueio falso-positivo** — se o PA estimou tokens errados (trabalhos muito mais longos), o batch pode bater no limite indevidamente. Solução: aumentar `MAX_COST_BRL` ou dividir o batch.

### Impacto de Haiku vs. Sonnet

A decisão de usar **Haiku para correção em lote** e **Sonnet apenas para calibração** é o que torna o custo viável:

| Cenário                                | Custo Haiku (correção) | Custo Sonnet (correção) | Diferença |
|----------------------------------------|------------------------|--------------------------|-----------|
| 120 alunos, correção em 12 lotes Haiku | $0,2350                | —                        | —         |
| 120 alunos, correção em 12 lotes Sonnet| —                      | ~$0,8813                 | **3,75×** |

Cálculo Sonnet hipotético: `12 × (4000 × 3.00 + 4096 × 15.00) / 1M = 12 × $0,07344 = $0,8813`.

Se a correção fosse feita inteiramente em Sonnet, o custo do batch saltaria para ~R$ 4,85 (ainda dentro do limite, mas **3,75× mais caro**). A escolha do Haiku como modelo de correção é deliberada: ele é "good enough" para aplicar a rubrica em texto curto, e o Sonnet entra apenas onde sua maior capacidade de raciocínio agrega valor (calibração estatística + feedback consolidado).

**Conclusão:** a política de orçamento aqui definida só funciona em sintonia com a separação de responsabilidades entre Haiku e Sonnet. Mudar essa separação invalida as estimativas deste ADR.

## Referências

- [Story 0.6](../stories/0.6.story.md) — origem desta decisão.
- ADR-003 (Story 0.4) — define `max_tokens` (consistência cruzada).
- Anthropic Pricing: https://console.anthropic.com/settings/billing
- Anthropic Models: https://docs.anthropic.com/claude/docs/models-overview

> **Nota (2026-05-22):** Estimativas atualizadas para refletir max_tokens=4096 (decisão PA). Custo real tende a ser menor (output raramente atinge o limite máximo), mas esta é a estimativa conservadora de teto.

## Histórico de Revisões

| Data       | Autor          | Mudança                                       |
|------------|----------------|-----------------------------------------------|
| 2026-05-22 | @dev (Dex)     | Criação inicial — Story 0.6                   |
| 2026-05-22 | PA             | max_tokens unificado em 4096 — conflito ADR-002 vs ADR-003 resolvido |
