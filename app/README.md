# Assistente Interno NetBox (RAG + DeepAgent)

Aplicacao de assistente interno que consulta documentacao Markdown privada de um
repositorio corporativo para responder perguntas de configuracao de NetBox, com
backend compativel com OpenAI e front-end estilo Claude.

## Requisitos atendidos no projeto
- Agente com DeepAgents: `create_deep_agent` em `agent_core.py`.
- Minimo 2 tools customizadas: `tool_rag`, `tool_listar_fontes`, `tool_status_base`.
- Minimo 1 sub-agent: `especialista-netbox` e `especialista-importacao-yaml-netbox` (delegacao hierarquica via `subagents`).
- RAG com Postgres + pgvector local: tabela `chunks` + retrieval vetorial/lexical.
- Minimo 1 documento proprio anexado: `documentos_local/anexos/guia-inicial-netbox.md`.
- Pipeline completo: sincronizacao GitLab + ingestao + retrieval.
- Gera arquivo de importacao YAML em pasta persistente local: `NETBOX_IMPORTS_DIR` (default `documentos_local/imports`).

## Estrutura
- `agent_core.py`, nucleo compartilhado (config, sync GitLab, base pgvector, tool_rag, o agente).
- `server.py`, API compativel com OpenAI (`/v1/chat/completions`), o backend do chat.
- `app.py`, interface Gradio simples (alternativa rapida, usa o mesmo nucleo).
- `frontend/`, como plugar o assistant-ui (front-end estilo Claude) no backend.
- `docker-compose.yml`, `Dockerfile`, `.env.example`, `.github/`, `k8s/`.

## Passo 1, configurar `.env`
```bash
cp .env.example .env
```
Preencha pelo menos:
- `OPENAI_API_KEY` / `OPENAI_BASE_URL`
- `DOCS_REPO_TOKEN` (token read-only do GitLab corporativo)
- `DOCS_REPO_USERNAME` (padrao `oauth2`)
- `DOCS_REPO_URL` e `DOCS_REPO_BRANCH` (se necessario)
- `DOCS_LOCAL_ATTACH_DIR` para documentos locais anexados (default: `documentos_local/anexos`)
- `NETBOX_IMPORTS_DIR` para saida dos arquivos YAML de importacao (default: `documentos_local/imports`)

## Otimizacao de custo e tokens

Para reduzir custo e contexto enviado ao modelo, ajuste os parametros abaixo no `.env`:

```env
RAG_CACHE_TTL_SECONDS=300
RAG_CACHE_MAX_ENTRIES=256
MAX_RAG_CONTEXT_CHUNKS=6
```

Esses valores mantem cache de consultas repetidas e limitam o volume de contexto recuperado antes da resposta final.

## Passo 2, subir tudo (backend + UI) com Docker Compose
```bash
docker compose up --build
```
Sobe Postgres+pgvector, o `agent-api` (server.py) em `http://localhost:18080/v1`
e a UI Next.js em `http://localhost:3000`.
Sem Docker: `pip install -r requirements.txt` e `python server.py`.

Na inicializacao, o backend clona/atualiza automaticamente `DOCS_REPO_URL` em
`DOCS_LOCAL_DIR` e reingere os Markdown quando o commit muda.
No compose, `./documentos_local` e montado como volume do host em `/app/documentos_local`,
entao o clone do Git e os anexos ficam persistidos fora do container.
Se o clone remoto falhar, a ingestao continua com os arquivos de `DOCS_LOCAL_ATTACH_DIR`.

## Passo 3, front-end estilo Claude (assistant-ui) fora do Compose
O repositório já inclui a pasta `ui/` pronta. Para rodar fora do compose:
```bash
cd ../ui
cp .env.example .env.local
npm ci
npm run dev               # http://localhost:3000
```
O `route.ts` aponta o chat para o `agent-api` via `AGENT_API_URL`.
No build Docker da UI, a versão de Node é configurável por `UI_NODE_VERSION`
(`NODE_VERSION` no Dockerfile), para facilitar compatibilidade entre ambientes.

## Alternativa, Gradio (UI simples, sem Node)
`python app.py` sobe uma interface Gradio em `:7860` usando o mesmo nucleo. Outras
UIs OpenAI-compativeis (Open WebUI, LibreChat, Lobe Chat) tambem conectam no `agent-api`.

## CI/CD (GitHub Actions)
- `.github/workflows/ci.yml`, push/PR: compila `agent_core/app/server`, lint e `docker build`.
- `.github/workflows/deploy.yml`, tags `v*`: builda/publica a imagem do backend no GHCR
  e aplica os manifests. Configure o secret `KUBECONFIG` do repositorio.

## Kubernetes (`k8s/`)
`namespace`, `secret.example`, `postgres` (StatefulSet pgvector + volume), `app`
(o `agent-api`), `frontend` (assistant-ui, imagem sua) e `ingress`. Deploy manual:
```bash
kubectl apply -f k8s/namespace.yaml
kubectl -n agente-viagem create secret generic app-secrets --from-env-file=.env
kubectl apply -f k8s/postgres.yaml -f k8s/app.yaml -f k8s/frontend.yaml -f k8s/ingress.yaml
```

## Producao
- Nunca versione `.env`/Secret real; use gerenciador de segredos.
- O `server.py` e stateless (a UI manda o historico); para memoria por usuario, derive
  um `thread_id` por sessao.
- HTTPS/reverse proxy; restrinja o Postgres (rede/RBAC).
