// Front-end estilo Claude com assistant-ui (https://www.assistant-ui.com/).
// Crie o projeto com:  npx assistant-ui@latest create ui
// Depois SUBSTITUA o arquivo app/api/chat/route.ts do projeto por este, que
// aponta o chat para o SEU backend (server.py, compativel com OpenAI).
import { createOpenAI } from "@ai-sdk/openai";
import {
  streamText,
  convertToModelMessages,
  createUIMessageStreamResponse,
  toUIMessageStream,
  type UIMessage,
} from "ai";

export const maxDuration = 60;

const agente = createOpenAI({
  baseURL: process.env.AGENT_API_URL ?? "http://localhost:8000/v1",
  apiKey: process.env.AGENT_API_KEY ?? "sk-local-nao-usado",
});

export async function POST(req: Request) {
  const { messages }: { messages: UIMessage[] } = await req.json();

  const result = streamText({
    model: agente("nara"),
    messages: await convertToModelMessages(messages),
  });

  return createUIMessageStreamResponse({
    stream: toUIMessageStream({ stream: result.stream }),
  });
}
