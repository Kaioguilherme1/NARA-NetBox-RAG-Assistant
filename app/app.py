"""Aplicacao standalone do modelo NARA com interface Gradio.

Usa o nucleo compartilhado (agent_core). Roda igual local (python app.py) e em
container (docker compose up). A interface fica em http://localhost:7860.
"""
import gradio as gr
from langchain_core.messages import AIMessageChunk

from agent_core import construir_agente, decidir_rota, resposta_rapida

agente = construir_agente(persistente=True)


def responder(mensagem, historico):
    """Streaming da resposta do agente, token a token."""
    pergunta = (mensagem or "").strip()
    rota = decidir_rota(pergunta)
    if rota == "light":
        resposta = resposta_rapida()
        yield resposta
        return

    cfg = {"configurable": {"thread_id": "web"}}
    parcial = ""
    for token, _meta in agente.stream(
        {"messages": [{"role": "user", "content": mensagem}]},
        cfg,
        stream_mode="messages",
    ):
        if isinstance(token, AIMessageChunk) and token.content:
            parcial += token.content
            yield parcial


demo = gr.ChatInterface(
    fn=responder,
    title="NARA",
    description="Assistente interno para NetBox e padroes de documentacao institucional.",
)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
