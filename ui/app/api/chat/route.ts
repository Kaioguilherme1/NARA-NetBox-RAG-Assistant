// Aponta o chat para o backend do curso (server.py, API compativel com OpenAI).
// Usa .chat(...) para falar com /v1/chat/completions (o backend nao implementa a Responses API).
import { createOpenAI } from "@ai-sdk/openai";
import { streamText, convertToModelMessages, type UIMessage } from "ai";

const agente = createOpenAI({
  baseURL: process.env.AGENT_API_URL ?? "http://localhost:18080/v1",
  apiKey: process.env.AGENT_API_KEY ?? "sk-local-nao-usado",
});

export async function POST(req: Request) {
  const { messages }: { messages: UIMessage[] } = await req.json();

  const result = streamText({
    model: agente.chat("nara"),
    messages: await convertToModelMessages(messages),
  });

  return result.toUIMessageStreamResponse({
    onError: (error) => (error instanceof Error ? error.message : String(error)),
  });
}
