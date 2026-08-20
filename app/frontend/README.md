# Front-end estilo Claude com assistant-ui

O assistant-ui (https://www.assistant-ui.com/) e uma biblioteca React para chats de
IA, o visual mais parecido com o claude.ai. Aqui ele e o front-end do modelo NARA,
conversando com o backend `server.py` (API compativel com OpenAI).

## Passos
1. Suba o backend (na pasta do app): `docker compose up --build`
   (ou `python server.py`). Ele fica em http://localhost:8000/v1
2. Crie o projeto do front-end (Next.js):
   ```bash
   npx assistant-ui@latest create ui
   cd ui
   npm install @ai-sdk/openai
   ```
3. Aponte o chat para o seu backend:
   - Substitua `ui/app/api/chat/route.ts` pelo `route.ts` desta pasta.
   - Crie `ui/.env.local` a partir de `.env.local.example`:
     ```
     AGENT_API_URL=http://localhost:8000/v1
     AGENT_API_KEY=sk-local-nao-usado
     ```
4. Rode o front-end:
   ```bash
   npm run dev
   ```
   Abra http://localhost:3000, chat estilo Claude, conversando com o modelo NARA.

## Deploy
O `ui/` e um app Next.js: `npm run build` e sirva (Vercel, Node ou container). Em
producao, aponte `AGENT_API_URL` para o endereco interno do `agent-api`. Ha um
manifesto de exemplo em `k8s/frontend.yaml`.
