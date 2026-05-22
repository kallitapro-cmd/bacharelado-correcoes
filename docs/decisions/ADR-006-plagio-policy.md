# ADR-006 — Política de Detecção e Tratamento de Plágio

**Data:** 2026-05-22
**Status:** Aceito
**Autores:** @architect (Aria), @dev (Dex)
**Stakeholders consultados:** Professor Assistente (PA) — perfil pedagógico

---

## Contexto

O sistema de correção acadêmica processa, em cada execução (batch), trabalhos entregues por uma turma de alunos (tipicamente até 120 alunos por disciplina). Em contexto universitário, há risco real de:

- **Cópia direta entre alunos** — um aluno entrega o trabalho de outro com pequenas modificações.
- **Trabalhos em grupo entregues individualmente** — mesmo arquivo submetido por múltiplos alunos.
- **Reutilização de trabalhos antigos** — texto copiado de turmas anteriores (fora do escopo desta versão, pois o batch é fechado por execução).
- **Uso de IA generativa** — texto produzido por ChatGPT, Claude, Gemini ou similares.

A decisão de tratar (ou não tratar) cada um desses casos é **pedagógica e institucional**, não técnica. O sistema pode auxiliar fornecendo evidências, mas a decisão final sobre nota, advertência ou processo disciplinar é **exclusivamente do PA**, que conhece o contexto da disciplina, o histórico dos alunos e a política da instituição.

Este ADR formaliza:

1. Qual algoritmo de detecção será usado.
2. Qual o threshold de similaridade que gera uma flag.
3. O que o PA vê quando há suspeita de plágio.
4. Como o sistema se comporta diante de trabalhos em grupo.
5. Se a detecção de IA generativa será implementada (e por quê).
6. A garantia explícita de não-punição automática.

---

## Decisão

O sistema **detecta similaridade textual** entre trabalhos do mesmo batch usando `difflib.SequenceMatcher` (biblioteca padrão do Python) e **levanta uma flag visual** para o PA quando dois trabalhos têm similaridade ≥ 70%. O sistema **nunca altera notas automaticamente** por suspeita de plágio. A decisão sobre consequências é 100% do PA.

A detecção de **IA generativa** **não será implementada** nesta versão. A justificativa está na seção "Detecção de IA Generativa".

---

## Algoritmo de Detecção

### Ferramenta

`difflib.SequenceMatcher` da biblioteca padrão Python.

### Justificativa da escolha

| Critério | `difflib.SequenceMatcher` | Alternativas (Levenshtein, embedding, API externa) |
|----------|---------------------------|-----------------------------------------------------|
| Dependências externas | **Nenhuma** (stdlib) | Pacote extra (`python-Levenshtein`) ou serviço pago |
| Custo | **Zero** | Pacote: zero; API: USD/chamada |
| Funciona offline | **Sim** | Sim (libs locais) ou Não (API) |
| Privacidade (texto sai do sistema) | **Não sai** | Não sai (libs locais) ou **Sai** (API) — conflita com ADR-004 |
| Precisão para textos curtos/médios | Adequada | Maior (embedding), porém custo desproporcional ao MVP |
| Velocidade para batch de 120 alunos | Aceitável (~7.140 pares < 30s) | Variável |

`SequenceMatcher` é "good enough" para o MVP: detecta cópia literal e quase-literal, que é o caso de uso dominante. Detecção semântica (paráfrase, tradução, reescrita) fica como roadmap futuro.

### Cálculo da similaridade

Para cada par de trabalhos `(a, b)` no batch:

```python
import difflib

def calcular_similaridade(texto_a: str, texto_b: str) -> float:
    """
    Retorna razão de similaridade entre 0.0 e 1.0.
    1.0 = textos idênticos
    0.0 = textos completamente diferentes
    """
    matcher = difflib.SequenceMatcher(None, texto_a, texto_b)
    return matcher.ratio()
```

### Pré-processamento (antes de comparar)

Para reduzir falsos positivos triviais:

1. **Normalizar whitespace** — múltiplos espaços/quebras → espaço único.
2. **Lowercase** — comparação case-insensitive.
3. **Remover caracteres não-textuais** — números de página, headers/footers detectáveis.
4. **NÃO remover stopwords** — manteria viés contra textos curtos.

### Algoritmo do batch

```python
def detectar_plagio_no_batch(trabalhos: list[Trabalho], threshold: float = 0.70) -> list[ParPlagio]:
    """
    Compara todos os pares O(n²). Para n=120: ~7.140 comparações.
    Retorna pares com similaridade >= threshold.
    """
    pares_suspeitos = []
    for i in range(len(trabalhos)):
        for j in range(i + 1, len(trabalhos)):
            sim = calcular_similaridade(
                preprocess(trabalhos[i].texto),
                preprocess(trabalhos[j].texto),
            )
            if sim >= threshold:
                pares_suspeitos.append(ParPlagio(
                    aluno_a=trabalhos[i].aluno_id,
                    aluno_b=trabalhos[j].aluno_id,
                    similaridade=sim,
                ))
    return pares_suspeitos
```

### Performance esperada

Para um batch típico de 120 alunos com trabalhos de ~5.000 caracteres cada:
- Comparações: `120 * 119 / 2 = 7.140` pares
- Tempo médio por comparação: ~3-5ms
- Tempo total: ~25-35 segundos

Aceitável dentro da janela de processamento do batch (que já tem operações mais lentas, como chamadas à IA).

---

## Threshold

### Valor adotado: **70% (0.70)**

### Justificativa

| Faixa de similaridade | Interpretação | Ação do sistema |
|-----------------------|---------------|-----------------|
| 0% – 49% | Conteúdo independente; sobreposição apenas em tópicos ou citações curtas | **Nenhuma flag** |
| 50% – 69% | Sobreposição substancial; pode ocorrer em respostas a questões objetivas, citações longas legítimas, ou template compartilhado | **Nenhuma flag** (decidiu-se priorizar precisão sobre recall) |
| 70% – 89% | Sobreposição alta; coincidência rara em redações livres; provável cópia ou colaboração indevida em trabalho individual | **Flag amarela** — PA deve revisar |
| 90% – 100% | Sobreposição muito alta; cópia direta com mínimas alterações ou trabalho idêntico | **Flag vermelha** — PA deve revisar prioritariamente |

### Por que não 80% ou 60%?

- **80% seria muito permissivo:** estudos sobre plágio acadêmico (e a experiência do PA consultado) indicam que cópias verdadeiras frequentemente caem em 70-85% após pequenas edições para "disfarçar". Subir o threshold deixaria escapar casos óbvios.
- **60% seria muito sensível:** trabalhos sobre o mesmo tema, com a mesma bibliografia obrigatória e mesma estrutura de seções podem legitimamente atingir 55-65% sem cópia real. Geraria muitos falsos positivos.
- **70% é o ponto de equilíbrio** sugerido pelo PA e suportado pelos casos observados em fixtures.

### Configurabilidade

O threshold é **um parâmetro configurável** na execução do batch. O default é 0.70, mas o PA pode ajustar via parâmetro (ex.: 0.85 para trabalhos sobre temas muito padronizados, 0.65 para redações livres). A justificativa do ajuste fica registrada nos logs do batch para auditoria.

### Severidade visual

Duas faixas visuais para o PA, ambas considerando o mesmo threshold conceitual (≥70%):

- **70% – 89%** → flag amarela (revisar)
- **90% – 100%** → flag vermelha (revisar prioritariamente)

---

## Comportamento para Grupos

### Política adotada: **ambos os lados são flaggados**

Quando o par `(aluno_A, aluno_B)` atinge similaridade ≥ 70%, **ambos** os alunos recebem a flag, com o mesmo nível de severidade.

### Justificativa

1. **O sistema não sabe quem copiou de quem.** Determinar precedência exigiria timestamps de entrega confiáveis (o que não temos garantia de existir nas planilhas do PA) **e** uma definição pedagógica de que "quem entrega depois é o copiador" — o que não corresponde necessariamente à realidade.
2. **Tratamento igual evita injustiça automática.** Punir só o "mais recente" pode condenar o aluno que escreveu primeiro mas entregou depois.
3. **O PA tem o contexto.** É o PA quem sabe se aquele par é de um grupo legítimo, se um dos alunos tem histórico de cópia, ou se há outra explicação contextual.

### Trabalhos em grupo (declarados)

**Esta versão NÃO suporta declaração de grupos** na planilha do PA. Portanto:

- Se a atividade é em grupo, **trabalhos do mesmo grupo serão flaggados** (similaridade naturalmente alta).
- O PA verá a flag, reconhecerá o par como "membros do mesmo grupo" e poderá **ignorar manualmente** ao avaliar.
- **Falso positivo aceito conscientemente** — o custo de ignorar manualmente alguns pares é menor que o custo de implementar suporte a grupos antes de validar a UX.

**Roadmap futuro (não nesta versão):** adicionar coluna opcional `grupo` na planilha → sistema agrupa alunos e suprime flags **dentro do mesmo grupo declarado**, mas mantém flags entre grupos diferentes.

---

## O que o PA Vê

### No card do aluno (visão lista)

- **Badge vermelho** no canto superior direito do card com o texto: `PLÁGIO: 84% com Grupo G3` (exemplo).
- Cor da badge:
  - 70% – 89%: **amarelo**
  - 90% – 100%: **vermelho**
- O texto sempre inclui:
  - Porcentagem de similaridade (arredondada a 1 decimal).
  - Identificador do(s) par(es) similar(es) — RA, nome ou rótulo de grupo, conforme disponível na planilha.
- Se houver **múltiplos pares** acima do threshold, a badge mostra o **maior** percentual e indica o número de pares: `PLÁGIO: 91% (3 pares)`.

### Ao clicar na badge (detalhe)

Abre um painel lateral com:

1. **Lista de pares similares**, ordenada por percentual descendente.
2. Para cada par: nome do outro aluno, percentual exato, link para abrir os dois trabalhos lado a lado.
3. **Visualização side-by-side** dos trechos mais similares (diff highlight do `difflib`).
4. **Ação disponível ao PA:** marcar manualmente como "Falso positivo (grupo)", "Falso positivo (revisado)" ou "Confirmado". Esta marcação **não altera a nota**; é apenas um registro para o próprio PA.

### O que a badge NÃO faz

- ❌ Não altera a nota do aluno automaticamente.
- ❌ Não bloqueia a exportação da planilha.
- ❌ Não envia notificação ao aluno ou à secretaria.
- ❌ Não persiste em base de dados externa (consistente com ADR-004 — retenção zero).

---

## Detecção de IA Generativa

### Decisão: **NÃO implementar nesta versão**

### Justificativa

Foram avaliadas três alternativas:

| Alternativa | Prós | Contras | Veredicto |
|-------------|------|---------|-----------|
| **Heurística interna** (perplexidade baixa, padrões de frase, ausência de erros) | Sem custo, sem dependência externa, privacidade preservada | **Precisão muito baixa** — falsos positivos em textos bem escritos, falsos negativos em texto IA editado. Risco real de injustiça com alunos disléxicos, estrangeiros ou bilíngues que naturalmente escrevem em padrões mais uniformes. | **Rejeitada** |
| **API externa** (GPTZero, Originality.ai, Copyleaks AI Detector) | Maior precisão declarada | Custo por requisição (~USD 0.01–0.03/trabalho × 120/batch × N batches/mês = significativo). **Texto sai do sistema** — conflita diretamente com ADR-004 (retenção zero / LGPD). Dependência de terceiro com viés conhecido contra não-nativos do inglês. | **Rejeitada** |
| **Deferir / não implementar** | Sem custo, sem risco de injustiça por classificador ruim, sem violação de LGPD | Sistema não alerta automaticamente sobre IA — PA depende de inspeção manual e do seu próprio julgamento | **Adotada** |

### Decisão consciente, com justificativas explícitas

1. **Precisão é o gargalo.** Mesmo as melhores APIs comerciais têm taxas de falso positivo entre 1% e 9% reportadas em estudos independentes (OpenAI, 2026; Stanford HAI, 2026). Aplicado a um batch de 120 alunos, isso significa potencialmente **1 a 11 alunos acusados injustamente por execução** — risco inaceitável quando a consequência é acadêmica.
2. **Viés conhecido contra grupos vulneráveis.** Detectores de IA têm taxa de falso positivo significativamente maior para escritores não-nativos do idioma e para textos seguindo estruturas acadêmicas padronizadas — exatamente o perfil de muitos alunos universitários.
3. **Conflito com ADR-004 (privacidade/LGPD).** Enviar texto de alunos a serviços terceiros sem consentimento explícito e específico para essa finalidade viola o princípio de minimização de dados.
4. **Esforço desproporcional ao valor entregue no MVP.** O PA tem como objetivo principal corrigir trabalhos — adicionar uma feature de baixa confiança e alto risco não está no caminho crítico.

### Reserva no schema (para o futuro)

O schema definido em ADR-002 já reserva o campo `flags` (lista de strings) na resposta do Clone. Quando/se a detecção de IA for implementada no futuro, a flag `ia_generativa_suspeita` poderá ser adicionada **sem mudança de contrato**. Isto preserva opcionalidade futura sem custo presente.

### Quando reavaliar

Esta decisão deve ser reavaliada quando:
- Surgir uma técnica local (sem API externa) com precisão > 95% e taxa de falso positivo < 1%, validada em estudos independentes.
- OU houver demanda forte e consistente do PA após uso em produção do MVP, **e** a instituição assumir formalmente o risco de falsos positivos.
- OU surgir framework legal/institucional que **obrigue** a detecção, com responsabilidade legal transferida.

---

## Garantia Explícita: Sem Punição Automática

Esta seção é **normativa** e tem precedência sobre qualquer outra documentação ou implementação:

> **NENHUMA nota é alterada automaticamente pelo sistema em razão de suspeita de plágio.**
>
> **NENHUM aluno é reprovado, advertido ou marcado como infrator automaticamente.**
>
> **Toda e qualquer ação consequente (alterar nota, abrir processo, advertir o aluno, comunicar a secretaria) é exclusivamente do Professor Assistente, após análise consciente da evidência apresentada pelo sistema.**

O sistema atua estritamente como **ferramenta de evidência**: levanta a flag, mostra os textos lado a lado, fornece o percentual. Tudo o que vem depois é decisão humana.

Esta garantia se aplica a:
- Detecção de plágio (este ADR).
- Detecção de IA generativa (caso seja implementada no futuro).
- Qualquer outra heurística automatizada de detecção de "irregularidade" que venha a ser adicionada.

Implementação: o módulo de detecção **não tem acesso de escrita** ao campo `nota` no schema do trabalho. A separação de responsabilidades é estrutural, não apenas convencional.

---

## Consequências

### Positivas

- **Detecção de cópia direta funcional no MVP** sem dependências externas, sem custo e sem comprometer privacidade.
- **PA mantém autonomia total** sobre decisões disciplinares — alinhado com o princípio de "sistema como assistente, nunca juiz".
- **Compatibilidade com ADR-004 (LGPD):** nenhum dado sai do sistema para detecção; processamento 100% local.
- **Schema preparado para extensão futura** sem breaking change (campo `flags` já existente em ADR-002).

### Negativas / Aceitas conscientemente

- **Falsos positivos em trabalhos em grupo** — ausência de coluna "grupo" na planilha gera flags para colegas legítimos. **Mitigação:** UX prevê marcação manual de "falso positivo (grupo)". **Roadmap futuro:** suporte a grupos declarados.
- **Falsos positivos em trabalhos com bibliografia obrigatória extensa** — citações longas e padronizadas podem inflar a similaridade. **Mitigação:** PA vê os textos lado a lado e pode contextualizar.
- **Sem detecção de paráfrase / cópia traduzida** — `SequenceMatcher` é literal; aluno que reescreve manualmente não é detectado. **Aceito:** detecção semântica fica fora do MVP.
- **Sem detecção de IA generativa** — risco conhecido de uso indevido de IA não é mitigado pelo sistema. **Aceito:** justificativa detalhada na seção respectiva.
- **Performance O(n²)** — em turmas muito grandes (>500 alunos), o tempo cresce quadraticamente. **Aceito:** turmas típicas do contexto-alvo são ≤120 alunos. Para turmas maiores, otimizações (LSH, MinHash) ficam como roadmap.

### Riscos residuais

| Risco | Probabilidade | Impacto | Mitigação |
|-------|---------------|---------|-----------|
| PA confundir flag com "veredicto" e punir sem revisar | Média | Alto | UI deixa claro que é alerta, não veredicto; mensagem explícita no painel de detalhe |
| Aluno acusado por similaridade legítima (bibliografia comum) | Média | Alto | Visualização side-by-side permite ao PA contextualizar antes de decidir |
| Threshold inadequado para uma disciplina específica | Baixa | Médio | Threshold é configurável por execução |
| Falso negativo (cópia bem disfarçada com paráfrase) | Alta | Baixo–Médio | Aceito no MVP; PA pode inspecionar manualmente se desconfiar |

---

## Parâmetros para Sprint 1 (insumo)

A implementação do detector no Sprint 1 deve respeitar:

| Parâmetro | Valor |
|-----------|-------|
| Biblioteca | `difflib.SequenceMatcher` (stdlib Python) |
| Threshold default | `0.70` |
| Threshold configurável | Sim, parâmetro do batch |
| Pré-processamento | Normalize whitespace, lowercase, remove non-textual |
| Complexidade | O(n²) aceitável para n ≤ 120 |
| Severidade visual | 70-89% amarelo, 90-100% vermelho |
| Comportamento para grupos | Ambos flaggados |
| Suporte a grupos declarados | **Não** nesta versão |
| Detecção de IA generativa | **Não** nesta versão |
| Permissão de alterar nota automaticamente | **Proibida estruturalmente** |
| Campo no schema | `flags: list[str]` (de ADR-002) — valor adicionado: `"plagio_suspeito"` |

---

## Referências

- ADR-002 — Contrato Clone↔Wrapper (campo `flags` no schema)
- ADR-004 — LGPD e Retenção Zero (privacidade e processamento local)
- Story 0.7 — Definir política de detecção de plágio (`docs/stories/0.7.story.md`)
- Python docs — `difflib.SequenceMatcher` (https://docs.python.org/3/library/difflib.html)

---

## Histórico

| Data | Autor | Mudança |
|------|-------|---------|
| 2026-05-22 | @architect (Aria) + @dev (Dex) | Versão inicial — Status: Aceito |
