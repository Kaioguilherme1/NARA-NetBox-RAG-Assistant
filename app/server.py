"""Servidor compativel com a API da OpenAI que expoe o modelo NARA.

Assim qualquer UI open-source estilo Claude (Open WebUI, LibreChat, Lobe Chat)
conecta como se fosse um "modelo", sem depender de langgraph dev. Endpoints:
GET /v1/models e POST /v1/chat/completions (com streaming via SSE).
"""
import json
import time
import uuid

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import AIMessageChunk

from agent_core import construir_agente, decidir_rota, resposta_rapida

# A UI manda o historico completo a cada requisicao, entao o backend e stateless.
agente = construir_agente(persistente=False)
MODEL_ID = "nara"

app = FastAPI(title="NARA, API compativel com OpenAI")


@app.get("/v1/models")
def listar_modelos():
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "owned_by": "curso"}]}


class ChatRequest(BaseModel):
    messages: list
    stream: bool = False
    model: str = MODEL_ID


def _historico(req_messages):
    """Mantem apenas role + content textual (ignora conteudo multimodal)."""
    saida = []
    for m in req_messages:
        conteudo = m.get("content")
        if isinstance(conteudo, str) and m.get("role") in ("system", "user", "assistant"):
            saida.append({"role": m["role"], "content": conteudo})
    return saida


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest):
    cid = "chatcmpl-" + uuid.uuid4().hex[:24]
    criado = int(time.time())
    cfg = {"configurable": {"thread_id": uuid.uuid4().hex}}
    mensagens = _historico(req.messages)
    ultima = mensagens[-1]["content"] if mensagens else ""
    rota = decidir_rota(ultima)

    if rota == "light":
        conteudo = resposta_rapida()
        payload = {
            "id": cid, "object": "chat.completion", "created": criado, "model": MODEL_ID,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": conteudo},
                         "finish_reason": "stop"}],
        }
        if not req.stream:
            return payload

        def gerar():
            pedaco = {
                "id": cid, "object": "chat.completion.chunk", "created": criado, "model": MODEL_ID,
                "choices": [{"index": 0, "delta": {"content": conteudo}, "finish_reason": None}],
            }
            yield "data: " + json.dumps(pedaco, ensure_ascii=False) + "\n\n"
            fim = {
                "id": cid, "object": "chat.completion.chunk", "created": criado, "model": MODEL_ID,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield "data: " + json.dumps(fim) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gerar(), media_type="text/event-stream")

    if not req.stream:
        resultado = agente.invoke({"messages": mensagens}, cfg)
        conteudo = resultado["messages"][-1].content
        return {
            "id": cid, "object": "chat.completion", "created": criado, "model": MODEL_ID,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": conteudo},
                         "finish_reason": "stop"}],
        }

    def gerar():
        for token, _meta in agente.stream({"messages": mensagens}, cfg, stream_mode="messages"):
            if isinstance(token, AIMessageChunk) and token.content:
                pedaco = {
                    "id": cid, "object": "chat.completion.chunk", "created": criado, "model": MODEL_ID,
                    "choices": [{"index": 0, "delta": {"content": token.content}, "finish_reason": None}],
                }
                yield "data: " + json.dumps(pedaco, ensure_ascii=False) + "\n\n"
        fim = {
            "id": cid, "object": "chat.completion.chunk", "created": criado, "model": MODEL_ID,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield "data: " + json.dumps(fim) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gerar(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
