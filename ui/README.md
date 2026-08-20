# UI (assistant-ui) do NARA

Esta UI conversa com o backend OpenAI-compatível do projeto via `AGENT_API_URL`.

## Execução local

1. Crie `ui/.env.local` com:

```env
AGENT_API_URL=http://localhost:18080/v1
AGENT_API_KEY=sk-local-nao-usado
```

2. Instale dependências e rode:

```bash
npm ci
npm run dev
```

Acesse `http://localhost:3000`.

## Build Docker (compatível com versão de Node configurável)

O Dockerfile da UI aceita `NODE_VERSION` como argumento de build.

```bash
docker build --build-arg NODE_VERSION=22-bookworm-slim -t nara-ui .
```

No `docker compose` (`app/docker-compose.yml`), a versão pode ser definida via:

```env
UI_NODE_VERSION=22-bookworm-slim
```
