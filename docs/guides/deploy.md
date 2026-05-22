# Deploy no Streamlit Cloud

Guia passo a passo para publicar o **Corretor Acadêmico** no Streamlit
Community Cloud, a plataforma gratuita oficial do Streamlit
([share.streamlit.io](https://share.streamlit.io)).

O fluxo é desenhado para o PA (Professor Assistente) — não exige
conhecimento de DevOps, apenas uma conta GitHub e a chave da API
Anthropic.

---

## Pré-requisitos

Antes de iniciar, garanta que você tem:

| Item | Como obter |
|------|------------|
| Conta no GitHub | [github.com/signup](https://github.com/signup) |
| Repositório com o código do Corretor Acadêmico | Fork ou push direto |
| Conta no Streamlit Cloud | [share.streamlit.io](https://share.streamlit.io) (login com GitHub) |
| Chave da API Anthropic | [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) |
| `config.yaml` real (auth local) | Gerado conforme `config.yaml.example` (Story 1.2) |

> **Importante:** O Streamlit Cloud não oferece disco persistente — todos
> os dados de aluno vivem apenas em memória durante a sessão (ADR-004).
> Isso é uma decisão arquitetural deliberada, alinhada com a política de
> Retenção Zero.

---

## Passo 1 — Preparar o repositório no GitHub

1. **Fork ou push do projeto** para um repositório GitHub seu (público
   ou privado — Streamlit Cloud suporta ambos):

   ```bash
   # Caso ainda não tenha o repo remoto:
   git remote add origin git@github.com:<seu-usuario>/bacharelado-correcoes.git
   git push -u origin main
   ```

2. **Confirme que estes arquivos estão versionados** (sem secrets!):

   - `app.py` — entrypoint Streamlit
   - `requirements.txt` — dependências Python pinadas
   - `packages.txt` — pacotes APT (tesseract-ocr, etc.)
   - `.streamlit/config.toml` — tema e configuração do servidor
   - `.streamlit/secrets.toml.example` — exemplo (sem valores reais)
   - `config.yaml.example` — exemplo do auth (sem credenciais reais)
   - `src/` — código da aplicação

3. **Confirme que estes arquivos NÃO estão versionados** (o `.gitignore`
   já os bloqueia, mas vale conferir):

   - `.streamlit/secrets.toml` — secrets reais
   - `config.yaml` — credenciais hashed do auth
   - `.env*` — variáveis de ambiente locais

   Verifique rapidamente com:

   ```bash
   git ls-files | grep -E '(secrets\.toml|config\.yaml|\.env)' | grep -v example
   ```

   Se a saída for vazia, está correto.

---

## Passo 2 — Criar a app no Streamlit Cloud

1. Acesse [share.streamlit.io](https://share.streamlit.io) e faça
   login com sua conta GitHub.

2. Clique em **"New app"** no canto superior direito.

3. Preencha o formulário **Deploy an app**:

   | Campo | Valor |
   |-------|-------|
   | **Repository** | `<seu-usuario>/bacharelado-correcoes` |
   | **Branch** | `main` |
   | **Main file path** | `app.py` |
   | **App URL** (opcional) | `corretor-academico` (ou nome de sua escolha) |

4. **Ainda NÃO clique em Deploy.** Antes, configure os secrets — sem
   eles, a app vai exibir erro de startup.

---

## Passo 3 — Configurar os Secrets

Os secrets do Streamlit Cloud equivalem ao seu `.streamlit/secrets.toml`
local — eles são injetados em `st.secrets` em runtime, sem nunca tocar o
filesystem versionado.

1. Ainda na tela de criação da app, clique em **"Advanced settings"**
   (ou, se a app já foi criada, vá em **Settings > Secrets**).

2. No campo **Secrets** cole o conteúdo a seguir, substituindo cada
   valor de exemplo pelo valor real:

   ```toml
   # Chave da API Anthropic (obrigatória)
   ANTHROPIC_API_KEY = "sk-ant-..."

   # Chave de cookie do streamlit-authenticator (obrigatória, >= 32 chars)
   AUTH_COOKIE_KEY = "<gere com: python -c 'import secrets; print(secrets.token_hex(32))'>"

   # Hard limit de custo por sessão em R$ (opcional, padrão 15.0) — ADR-005
   MAX_COST_BRL = "15.0"
   ```

3. **Atenção:** o valor de `ANTHROPIC_API_KEY` é o segredo mais sensível
   da aplicação. Ele só deve viver:
   - No painel **Settings > Secrets** do Streamlit Cloud, OU
   - No seu `.streamlit/secrets.toml` local (que está no `.gitignore`).

   Nunca compartilhe a chave, nunca cole em mensagens, e nunca commite
   em arquivos versionados. A política do projeto (ADR-004) proíbe
   inclusive logar a chave em mensagens de erro.

4. Clique em **Save** para gravar os secrets.

### Como configurar o `config.yaml` (auth) no Streamlit Cloud

O `streamlit-authenticator` (Story 1.2) espera ler um `config.yaml` com
credenciais hashed do PA. Como o Streamlit Cloud não oferece um campo
nativo para arquivos arbitrários, há duas estratégias:

**Estratégia A — Embarcar credenciais nos Secrets (recomendada para o MVP).**
Ao invés de manter `config.yaml` como arquivo, leia as credenciais
diretamente de `st.secrets` e construa o objeto de configuração em
runtime. Adicione ao painel Secrets:

```toml
[auth.credentials.usernames.pa_principal]
email = "pa@exemplo.edu.br"
name = "Professor Assistente"
password = "<hash bcrypt gerado por streamlit_authenticator.Hasher>"

[auth.cookie]
expiry_days = 1
key = "<mesmo valor de AUTH_COOKIE_KEY>"
name = "corretor_academico_cookie"
```

O carregador do auth (`src/auth/authenticator.py`) deve preferir
`st.secrets["auth"]` ao arquivo `config.yaml` quando ambos existirem —
isso evita versionar credenciais.

**Estratégia B — Subir `config.yaml` no repositório com hashes (NÃO
recomendado).** Tecnicamente funciona porque o `password` já está em
bcrypt e o `cookie.key` está externalizado, mas expõe o `email` e
`name` do PA em repositório (potencialmente público). Use apenas se o
repositório for privado e a organização aceitar o risco.

---

## Passo 4 — Deploy

1. Clique em **"Deploy!"**.

2. O Streamlit Cloud vai:
   - Clonar o repositório.
   - Instalar dependências de sistema (`packages.txt`).
   - Instalar dependências Python (`requirements.txt`).
   - Iniciar `app.py`.

   Este processo leva entre 2 e 5 minutos na primeira execução.

3. Acompanhe os logs em tempo real no painel — qualquer erro de
   instalação aparece aqui.

4. Quando o status mudar para **"Your app is live!"**, abra a URL
   exibida (formato `https://<app-name>.streamlit.app`).

---

## Passo 5 — Validar o deploy

Após a app estar live, valide:

| Verificação | Resultado esperado |
|-------------|--------------------|
| Página carrega sem stack trace | Banner LGPD ou tela de login visível |
| `ANTHROPIC_API_KEY` ausente nos secrets | App exibe `st.error` com orientação clara, **não crasha** |
| Login com PA válido | Acesso ao app principal |
| Login com PA inválido | Bloqueio após N tentativas (rate limit do auth) |
| Sidebar exibe o PA logado | "PA: nome_pa" + botão "Sair" |

> **Teste do startup check (importante):** Para confirmar que o check
> funciona, remova temporariamente o secret `ANTHROPIC_API_KEY` em
> Settings > Secrets, reinicie a app (botão "Reboot app" no menu) e
> verifique se a mensagem de erro aparece. Reponha o secret depois.

---

## Atualizando a app

Cada push para o branch configurado dispara redeploy automático.

```bash
git add .
git commit -m "feat: nova funcionalidade"
git push origin main
```

O Streamlit Cloud detecta o push e reinicia a app em ~30 segundos.

Para mudar a versão do Python ou variáveis de runtime, use o painel
**Settings > General** da app.

---

## Troubleshooting

### "ANTHROPIC_API_KEY não configurada"

Você esqueceu de preencher o secret. Acesse **Settings > Secrets**,
adicione `ANTHROPIC_API_KEY = "sk-ant-..."` e clique em "Reboot app".

### "tesseract: command not found" durante OCR

O Streamlit Cloud só instala `packages.txt` no primeiro deploy. Se
você adicionou um pacote APT depois, force um redeploy completo em
**Settings > General > Manage app > Reboot app**.

### App fica em "Waking up..."

Apps gratuitas do Streamlit Cloud hibernam após ~7 dias sem uso. O
primeiro acesso depois disso leva ~1 minuto para acordar — é
comportamento esperado da plataforma.

### Erro de import `from src.x import y`

Confirme que o repositório tem o arquivo `__init__.py` em cada pasta
sob `src/`. O Streamlit Cloud usa imports absolutos (a partir da raiz
do projeto), igual ao desenvolvimento local — não usar imports
relativos em `src/`.

### Custo da API parece alto

Confira o `MAX_COST_BRL` configurado nos Secrets. O padrão (R$ 15,00)
cobre folgadamente uma turma de 120 alunos (ADR-005). Se você está
batendo o limite com frequência, divida o batch em sub-batches
menores em vez de aumentar o limite.

---

## Próximos passos

- Para configurar um domínio customizado, considere o plano
  Streamlit Cloud Teams (pago) ou um proxy reverso (fora do escopo
  do MVP).
- CI/CD automatizado (testes antes do deploy) também está fora do
  escopo desta story — pode ser introduzido em sprint futuro via
  GitHub Actions.

---

## Referências

- **ADR-003** — Política de Temperature (parâmetros da API Anthropic)
- **ADR-004** — Privacidade e Retenção Zero (justifica o uso do
  Streamlit Cloud)
- **ADR-005** — Política de Orçamento (`MAX_COST_BRL`)
- **Streamlit Cloud Docs** — [docs.streamlit.io/deploy/streamlit-community-cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud)
- **Streamlit Secrets** — [docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)
