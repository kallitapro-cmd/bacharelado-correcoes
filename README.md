# Corretor Acadêmico

Sistema web Streamlit para correção automática de atividades acadêmicas usando
Anthropic Claude. Faz o upload de arquivos enviados pelos alunos (PDF, PPTX,
DOCX, imagens), normaliza o conteúdo, faz o matching com a planilha da turma
(RA → aluno) e gera notas/feedback em Excel.

## Pré-requisitos

- Python 3.11 ou superior
- `tesseract-ocr` instalado no sistema (com o pacote de idioma `por`)
- Conta Anthropic com chave de API válida

No Linux/WSL Ubuntu:

```bash
sudo apt update
sudo apt install -y tesseract-ocr tesseract-ocr-por libgl1
```

## Instalação local

```bash
git clone <repo-url> corretor-academico
cd corretor-academico
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

A aplicação ficará disponível em `http://localhost:8501`.

## Variáveis de ambiente / secrets

A configuração de runtime fica em `.streamlit/secrets.toml`. Copie o exemplo e
preencha com valores reais:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

| Chave | Obrigatório | Padrão | Descrição |
|-------|-------------|--------|-----------|
| `ANTHROPIC_API_KEY` | Sim | — | Chave de API do Claude (ADR-003). |
| `AUTH_COOKIE_KEY` | Sim | — | String aleatória (>= 32 chars) usada por `streamlit-authenticator`. |
| `MAX_COST_BRL` | Não | `15.0` | Hard limit de custo por sessão em R$ (ADR-005). |

Quando `ANTHROPIC_API_KEY` está ausente, a app exibe uma mensagem de
erro orientada no startup e interrompe o carregamento — não há crash
nem stack trace exposta ao usuário.

Para o sistema de autenticação local (será ativado na Story 1.2), copie
`config.yaml.example` para `config.yaml` e gere o hash bcrypt da senha do
usuário.

Nenhum desses arquivos deve ser commitado — o `.gitignore` já os bloqueia.

## Deploy

Para publicar a aplicação no Streamlit Cloud, consulte o guia completo:

- [`docs/guides/deploy.md`](docs/guides/deploy.md) — passo a passo do
  deploy (preparar o repositório, configurar secrets, validar a app).

## Documentação

- Arquitetura, ADRs e guias detalhados ficam em `docs/`
- Stories de desenvolvimento estão em `docs/stories/`
- Guias operacionais ficam em `docs/guides/`
  - [`deploy.md`](docs/guides/deploy.md) — deploy no Streamlit Cloud

## Estrutura do projeto

```
bacharelado-correcoes/
├── app.py                       # Entrypoint Streamlit
├── config.yaml.example          # Exemplo de credenciais (auth)
├── requirements.txt             # Dependências Python pinadas
├── packages.txt                 # Pacotes APT para Streamlit Cloud
├── .streamlit/
│   ├── config.toml              # Tema e configurações do Streamlit
│   └── secrets.toml.example     # Estrutura esperada de secrets
├── src/
│   ├── auth/                    # Autenticação (Story 1.2)
│   ├── converters/              # Conversores PDF/PPTX/DOCX/imagem
│   ├── matching/                # Normalização e matching de RA
│   ├── excel/                   # Leitura/escrita de planilhas
│   ├── corrector/               # Lógica de correção via Anthropic
│   ├── models/                  # Modelos pydantic compartilhados
│   └── utils/                   # Logger, auditoria, helpers
├── tests/
│   └── unit/                    # Testes unitários (pytest)
└── docs/
    ├── stories/                 # Stories do projeto
    ├── decisions/               # ADRs
    └── fixtures/                # Insumos de teste
```

## Como rodar testes

```bash
pytest -q
```

Cobertura:

```bash
pytest --cov=src --cov-report=term-missing
```

## Status

Em construção. Sprint 1 — fundação técnica. Story 1.1 entrega apenas o
esqueleto e a estrutura de pastas; nenhuma funcionalidade real está
implementada ainda.
