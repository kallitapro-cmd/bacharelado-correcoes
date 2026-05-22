# ADR-004 — Política de Privacidade e Retenção Zero

**Data:** 2026-05-22
**Status:** Aceito
**Autores:** @dev (Dex), @po (Pax)
**Base legal:** LGPD (Lei 13.709/2018) — Art. 7º, IX (legítimo interesse no contexto acadêmico institucional) e Art. 6º (princípios de finalidade, necessidade, livre acesso, qualidade dos dados, transparência, segurança, prevenção, não-discriminação e responsabilização)

---

## Contexto

O sistema **Corretor Acadêmico** manipula dados pessoais de alunos durante o fluxo de correção: **nome**, **RA** (Registro Acadêmico, 11 dígitos), **conteúdo dos trabalhos** entregues e **notas geradas**. Todos esses dados se classificam como **dados pessoais** sob a LGPD; o conteúdo dos trabalhos e as notas configuram **dados sensíveis** no contexto acadêmico, pois revelam desempenho individual em avaliações institucionais.

A arquitetura escolhida (Streamlit Cloud como runtime alvo) impõe restrições que **se alinham naturalmente com uma política de retenção zero**:

- O Streamlit Cloud **não oferece disco persistente** entre sessões — o filesystem do container é efêmero.
- O `st.session_state` vive apenas enquanto a aba do navegador estiver aberta e o servidor mantiver a sessão ativa.
- Não há banco de dados gerenciado no plano gratuito do Streamlit.

Diante disso, em vez de tratar a ausência de persistência como limitação, **adotamos como princípio arquitetural**: o sistema **não armazena** dados pessoais de alunos. Essa decisão simplifica radicalmente a conformidade com LGPD: sem armazenamento, não há necessidade de DPA (Data Processing Agreement), não há janela para vazamento pós-sessão e não há base de dados para sofrer breach. A obrigação de notificar a ANPD em caso de incidente de segurança (Art. 48) torna-se materialmente improvável.

A política precisa ser formalizada **antes** do Sprint 1 para que os desenvolvedores implementem os controles desde o primeiro commit, sem necessidade de retrofit posterior.

---

## Decisão

**Adota-se a política de Retenção Zero:** todos os dados pessoais de alunos vivem **exclusivamente em memória RAM**, durante a sessão Streamlit ativa, e são destruídos automaticamente quando a sessão encerra.

**Regras invioláveis (constraints arquiteturais):**

1. **Sem writes em disco** com dados de alunos. Nenhum `open(path, "w")`, nenhum `pickle.dump()`, nenhum `shelve`, nenhum SQLite com tabelas contendo PII.
2. **Sem banco de dados externo** com dados de alunos. Nada de PostgreSQL, Firestore, S3 ou similar.
3. **Excel de saída gerado in-memory** via `io.BytesIO()` e oferecido como download direto. Nunca salvo em filesystem.
4. **SQLite efêmero é permitido apenas em `/tmp`** (filesystem do container Streamlit Cloud, zerado entre sessões) e apenas para persistência intermediária de batch de correção durante a sessão. Deve ser explicitamente removido ao fim do processamento, mesmo que o `/tmp` já vá ser zerado.
5. **Logs nunca contêm PII de alunos** (ver seção "Sanitização de Logs").
6. **API key nunca aparece em logs ou stack traces** (ver seção "Sanitização de Logs").
7. **Banner de consentimento obrigatório** antes do primeiro upload de qualquer dado pessoal (ver seção "Banner de Consentimento").

---

## Mapeamento de Dados Pessoais

Inventário completo dos dados pessoais processados pelo sistema, suas localizações e ciclo de vida:

| Dado | Classificação LGPD | Onde vive | Por quanto tempo | Quem acessa |
|------|-------------------|-----------|------------------|-------------|
| Nome completo do aluno | PII | `st.session_state` (RAM) | Sessão ativa (≤ timeout do Streamlit Cloud) | Usuário logado + API Anthropic (durante chamada) |
| RA do aluno (11 dígitos) | PII (identificador único institucional) | `st.session_state` (RAM) | Sessão ativa | Usuário logado apenas |
| Conteúdo do trabalho (PDF/PPTX/DOCX) | Dado sensível acadêmico | `st.session_state` (RAM) + API Anthropic (em trânsito, TLS 1.2+) | Sessão ativa | Usuário logado + Anthropic (processamento, sem retenção contratual além do necessário ao serviço) |
| Nota gerada pela IA | Dado sensível acadêmico | `st.session_state` (RAM) + Excel em `BytesIO` | Sessão ativa, até download | Usuário logado apenas |
| Feedback textual gerado pela IA | Dado sensível acadêmico | `st.session_state` (RAM) + Excel em `BytesIO` | Sessão ativa, até download | Usuário logado apenas |
| Excel consolidado de saída | Dado sensível acadêmico | `io.BytesIO()` em RAM | Até o download (download dispara descarte) | Usuário logado apenas |
| SQLite efêmero de batch | Dado sensível acadêmico (em trânsito) | `/tmp/*.sqlite` no container Streamlit Cloud | Duração do batch; deletado ao fim do processamento | Processo Streamlit apenas |
| API key Anthropic (`sk-ant-*`) | Credencial técnica | `os.environ` / Streamlit Secrets | Runtime do processo | Sistema apenas — nunca exposta ao usuário, nunca logada |

**Observação sobre Anthropic:** o conteúdo dos trabalhos transita pela API Anthropic exclusivamente para fins de correção. Por contrato (Anthropic Trust Center) e configuração padrão de API tier, o conteúdo **não é usado para treinamento de modelos**. A Anthropic mantém logs operacionais por período limitado conforme sua política de privacidade. **Quando possível, evitar enviar o RA junto com o conteúdo do trabalho** — preferir referenciar o aluno por identificador interno opaco no prompt e desfazer a correlação no pós-processamento.

---

## Política de Retenção por Tipo de Dado

Resumo executivo da retenção e mecanismo de descarte:

| Dado | Armazenamento | Retenção | Mecanismo de descarte |
|------|--------------|---------|----------------------|
| Nome do aluno | `st.session_state` | Sessão ativa | Automático: garbage collector do Python ao encerrar sessão |
| RA do aluno | `st.session_state` | Sessão ativa | Automático: garbage collector do Python ao encerrar sessão |
| Conteúdo do trabalho | `st.session_state` + transferência TLS para Anthropic | Sessão ativa | Automático: GC do Python; Anthropic descarta conforme sua política |
| Nota e feedback | `st.session_state` + `BytesIO` | Sessão ativa, até download | Automático: GC do Python; `BytesIO` descartado após retorno do download |
| Excel gerado | `io.BytesIO()` | Apenas até disparar download | Automático: descartado ao sair do escopo da função |
| SQLite efêmero de batch | `/tmp/*.sqlite` (Streamlit Cloud) | Duração do batch | **Explícito**: `os.remove()` no `finally` do bloco de processamento; redundante com o reset do `/tmp` |
| API key | `os.environ` | Runtime do processo | Automático: removida quando processo termina |

**Princípios reforçados:**
- **Nenhum dado de aluno sobrevive ao encerramento da sessão** (tab fechada, timeout, restart do servidor).
- **Nenhuma cópia secundária** é criada (sem cache em disco, sem export para serviço externo).
- **Tempo de retenção é definido pela duração da sessão**, não por uma política temporal customizada.

---

## Sanitização de Logs

### Itens que NUNCA aparecem em logs

A lista abaixo é **vinculante** — qualquer linha de log que contenha um destes itens é uma **violação** que deve ser corrigida antes do merge:

1. **RA do aluno** (11 dígitos, em qualquer forma: completo, parcial, mascarado parcialmente).
2. **Nome completo do aluno** (primeiro nome, sobrenome, ou qualquer combinação que individualize).
3. **Nota individual** associada a qualquer identificador (RA, nome, ou índice posicional no batch que permita correlação).
4. **Feedback textual** gerado para um aluno específico.
5. **Conteúdo do trabalho** do aluno (qualquer trecho, mesmo fragmentado).
6. **API key Anthropic** (`sk-ant-*`) — nem completa, nem prefixo, nem hash, nem últimos 4 caracteres.
7. **Senha** ou hash de senha (caso o sistema evolua para login).
8. **Cookies de sessão** ou tokens de autenticação.

### O que PODE aparecer em logs

- Contadores agregados (ex.: `"processados: 47 alunos, sucesso: 45, erro: 2"`).
- IDs opacos de sessão (UUID gerado, sem correlação reversível com RA).
- Mensagens de erro **sem PII** (ex.: `"falha ao parsear PDF: arquivo corrompido"` — **não** `"falha ao parsear PDF de João Silva (RA 12345678901)"`).
- Métricas técnicas (latência, custo estimado de tokens, código HTTP).
- Timestamps.

### Implementação obrigatória — wrapper de logger

O Sprint 1 deve implementar um wrapper `safe_logger` que:

```python
# Pseudocódigo do wrapper que o @dev de Sprint 1 deve criar
import logging
import re

# Padrões de PII a serem redatados
_RA_PATTERN = re.compile(r"\b\d{11}\b")
_API_KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_-]+")

def _sanitize(msg: str) -> str:
    msg = _RA_PATTERN.sub("[REDACTED-RA]", msg)
    msg = _API_KEY_PATTERN.sub("[REDACTED-KEY]", msg)
    return msg

class SafeLogger:
    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def info(self, msg, *args, **kwargs):
        self._logger.info(_sanitize(msg % args if args else msg), **kwargs)

    def error(self, msg, *args, **kwargs):
        self._logger.error(_sanitize(msg % args if args else msg), **kwargs)
    # ... idem para debug/warning/critical
```

**Regras de uso:**
- **Toda** logagem do sistema usa `safe_logger`, nunca `logging` direto.
- Listas de nomes/RAs/notas **não devem ser passadas** ao logger nem mesmo via wrapper — preferir agregação (count) antes de logar.
- Para auditoria interna durante desenvolvimento (não produção), pode-se logar com IDs opacos e tabela de correlação mantida apenas em RAM.

### Sanitização de Stack Traces

Quando uma exceção ocorre durante o processamento de um aluno, **o stack trace bruto pode conter valores de variáveis com PII** (Python por padrão inclui o `repr()` de objetos em frames de exceção em alguns modos de log).

**Política obrigatória:**

1. **Nunca usar `traceback.format_exc()` direto em logs** quando o contexto inclui dados de aluno.
2. **Capturar a exceção, extrair apenas tipo e mensagem sanitizada**, descartar locals:

   ```python
   try:
       processar_aluno(aluno)
   except Exception as e:
       safe_logger.error(
           "Erro ao processar aluno em posição %d do batch: %s: %s",
           idx, type(e).__name__, _sanitize(str(e))
       )
       # NÃO fazer: safe_logger.error(traceback.format_exc())
   ```

3. **Para debug local profundo**, usar `pdb` em ambiente de desenvolvimento — nunca em produção/staging.
4. **Mensagens de erro mostradas ao usuário** (via `st.error()`) também passam pela sanitização — o usuário final não precisa ver o RA do aluno na mensagem de erro de outro aluno do batch.
5. **Configurar `sys.excepthook`** para o handler global redatar PII antes de qualquer escrita em stderr/stdout.

---

## Banner de Consentimento

### Texto definitivo (pronto para implementação)

O Sprint 1 deve renderizar **exatamente** o texto abaixo, em um modal/expander que **bloqueia a interação com upload de arquivos** até confirmação:

```
Este sistema processa dados pessoais de alunos (nome, RA, notas)
exclusivamente durante esta sessão. Nenhum dado é armazenado
permanentemente. Ao encerrar a sessão, todos os dados são
automaticamente removidos da memória.

Ao continuar, você confirma que tem autorização para processar
estes dados no contexto acadêmico institucional.

[Confirmar e continuar]
```

### Regras de exibição

| Regra | Comportamento |
|-------|---------------|
| Quando exibir | Na primeira interação da sessão, **antes** de qualquer upload ou input de dado de aluno |
| Bloqueio | O upload de arquivos só fica habilitado após clicar em "Confirmar e continuar" |
| Persistência da confirmação | Apenas dentro da sessão (em `st.session_state.consent_given = True`); nova sessão exibe novamente |
| Localização | Em destaque (modal preferido; expander como fallback se Streamlit não suportar modal) |
| Localidade | Português brasileiro (público-alvo é a coordenação acadêmica brasileira) |
| Acessibilidade | Texto em fonte legível (≥ 14px); botão com label explícito; foco no botão ao abrir |

### Trilha de auditoria opcional

Caso o PA institucional exija registro de consentimento, é aceitável registrar **apenas** `{timestamp, session_id_opaco, consent_given: True}` — nunca correlacionar com identidade do usuário/aluno. Essa trilha é opt-in e fora do escopo do MVP.

---

## Implicações de Implementação (para Sprint 1)

Lista de obrigações concretas que o `@dev` de Sprint 1 deve cumprir:

1. **Implementar `safe_logger`** (wrapper com redação de RA e API key) e substituir todas as chamadas a `logging` direto.
2. **Configurar `sys.excepthook`** para sanitizar stack traces globalmente.
3. **Renderizar o banner de consentimento** conforme texto e regras acima, com gate em `st.session_state.consent_given`.
4. **Excel de saída via `io.BytesIO()`** — proibido `to_excel(path)` com path em disco.
5. **Proibido `open(path, "w")`** com qualquer dado de aluno como conteúdo. Adicionar lint rule ou code review checklist para detectar.
6. **SQLite de batch (se necessário)** em `/tmp` apenas, com `os.remove()` explícito no `finally`.
7. **Não enviar RA para Anthropic** quando puder ser evitado — usar índice opaco no prompt.
8. **`st.session_state` é a única fonte de verdade** para dados de aluno durante a sessão; não criar variáveis globais módulo-nível que armazenem PII.
9. **Code review checklist** deve incluir: "Nenhum `print()`, `logging.*`, ou `traceback` direto escapando PII?".
10. **Testes** devem cobrir:
    - `safe_logger` redata RA (11 dígitos) corretamente.
    - `safe_logger` redata `sk-ant-*` corretamente.
    - Excel é gerado em `BytesIO`, não em disco (mock `open` com `side_effect=AssertionError`).
    - Banner bloqueia upload antes do consent.

---

## Consequências

### O que esta decisão SIMPLIFICA

- **Sem DPA (Data Processing Agreement)** com fornecedor de banco — não há banco com PII.
- **Sem notificação obrigatória à ANPD em caso de breach** (Art. 48 LGPD): sem armazenamento, breach pós-sessão é materialmente improvável; durante a sessão, o escopo do incidente é limitado a um usuário.
- **Sem política de backup/restore** de dados pessoais — não há o que backupar.
- **Sem implementação de "direito ao esquecimento" (Art. 18, VI)** — o esquecimento é automático e instantâneo.
- **Sem retenção mínima legal a considerar** — não armazenamos.
- **Deploy em Streamlit Cloud é trivial** — aproveita as restrições da plataforma a favor da política.

### O que esta decisão AINDA EXIGE cuidado

- **Disciplina rigorosa nos logs**: a regra "logs sem PII" só funciona se aplicada universalmente; uma única linha vazada quebra a política. Wrapper obrigatório + code review enforçam.
- **Sanitização de stack traces**: erros em produção tendem a vazar variáveis locais; `sys.excepthook` global é crítico.
- **Contrato com Anthropic**: o sistema confia que a Anthropic respeita sua política de não-treinamento e retenção limitada. Documentar em ADR futuro se mudarmos de provedor.
- **Memória do servidor entre sessões concorrentes**: o `st.session_state` é por sessão, mas vazamentos via variáveis globais em módulos compartilhados quebram o isolamento. Code review deve vetar variáveis globais com PII.
- **Downloads são responsabilidade do usuário**: após o download do Excel, o arquivo passa a viver na máquina do coordenador; a responsabilidade pela proteção física desse arquivo é institucional, fora do escopo do sistema. Documentar isso no banner ou no help.
- **Logs operacionais não-PII (latência, custo, erros)** continuam existindo e podem ser persistidos — não são afetados por esta política.
- **Treinar o usuário** (coordenação acadêmica) a não tirar prints de tela com dados que vazem fora da finalidade — escopo educacional, não técnico.

### Riscos residuais aceitos

| Risco | Mitigação | Aceito? |
|-------|----------|---------|
| Memória do container Streamlit Cloud sofrer dump em caso de crash | Streamlit Cloud não expõe dumps; restart limpa memória | Sim |
| Anthropic alterar política de retenção sem aviso | Monitorar Trust Center; ADR futuro se necessário trocar provedor | Sim |
| Usuário fazer screenshot do dashboard com PII visível | Responsabilidade institucional; fora do escopo técnico | Sim |
| Excel baixado e armazenado em local inseguro pelo usuário | Banner orienta; gestão do arquivo pós-download é institucional | Sim |
| Logs vazarem PII por bug no wrapper | Cobertura de testes do `safe_logger`; code review com checklist | Sim, com mitigação |

---

## Referências

- **LGPD**: [Lei 13.709/2018](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm), em especial Art. 6º (princípios), Art. 7º, IX (legítimo interesse), Art. 18 (direitos do titular), Art. 48 (notificação de incidente).
- **Anthropic Trust Center**: política de retenção e não-treinamento para clientes API tier.
- **Streamlit Cloud Architecture**: documentação oficial sobre filesystem efêmero e `st.session_state`.
- **ADR-002** (Contrato Clone↔Wrapper) — define quais campos seguem para a API; deve respeitar a política de minimização aqui descrita.
- **ADR-005** (Orçamento e Hard Limit) — métricas de custo podem ser logadas pois não são PII.

---

## Aprovação

| Papel | Nome | Data | Decisão |
|-------|------|------|---------|
| @sm (River) | — | 2026-05-22 | Story criada |
| @po (Pax) | — | 2026-05-22 | Story validada (GO 9.5/10) |
| @dev (Dex) | — | 2026-05-22 | ADR redigido |
| PA institucional | _pendente_ | _pendente_ | _pendente_ |

_ADR registrado em 2026-05-22 conforme Story 0.5 do Sprint 0._
