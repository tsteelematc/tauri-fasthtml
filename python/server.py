"""Native Agents — local LLM chat app served as the UI for the Tauri desktop shell."""

from pathlib import Path
from fasthtml.common import *
from llama_cpp import Llama

MODEL_PATH = Path(__file__).parent.parent / "models" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"

llm = Llama(model_path=str(MODEL_PATH), n_ctx=2048, verbose=False)

app, rt = fast_app(
    hdrs=[
        Style("""
            * { box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                display: flex; justify-content: center; align-items: flex-start;
                min-height: 100vh; margin: 0; padding: 2rem;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .chat-card {
                background: rgba(255,255,255,0.15);
                backdrop-filter: blur(10px);
                border-radius: 20px; padding: 2rem;
                width: 100%; max-width: 700px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.2);
            }
            h1 { margin: 0 0 1.5rem; font-size: 1.4rem; font-weight: 300; text-align: center; }
            textarea {
                width: 100%; padding: 0.75rem; border-radius: 10px;
                border: 2px solid rgba(255,255,255,0.4);
                background: rgba(255,255,255,0.1); color: white;
                font-size: 0.95rem; font-family: inherit; resize: vertical;
                min-height: 80px; outline: none;
            }
            textarea::placeholder { color: rgba(255,255,255,0.6); }
            textarea:focus { border-color: rgba(255,255,255,0.8); }
            button {
                margin-top: 0.75rem; width: 100%;
                padding: 0.6rem 1.5rem; font-size: 1rem;
                border: 2px solid white; border-radius: 10px;
                background: transparent; color: white; cursor: pointer;
                transition: background 0.2s;
            }
            button:hover { background: rgba(255,255,255,0.2); }
            .response-box {
                margin-top: 1.5rem; padding: 1rem;
                background: rgba(0,0,0,0.2); border-radius: 10px;
                min-height: 60px; white-space: pre-wrap; line-height: 1.6;
                font-size: 0.95rem;
            }
            .placeholder { color: rgba(255,255,255,0.5); font-style: italic; }
            .htmx-indicator { opacity: 0.6; }
        """)
    ]
)


def response_box(text: str = "", placeholder: bool = True):
    content = (
        Span("Response will appear here...", cls="placeholder")
        if placeholder and not text
        else text
    )
    return Div(content, cls="response-box", id="response")


@rt("/")
def get():
    return Titled(
        "Native Agents",
        Div(
            H1("🤖 Native Agents"),
            Form(
                Textarea(
                    name="prompt",
                    placeholder="Enter your prompt here...",
                    rows=4,
                    autofocus=True,
                ),
                Button(
                    "Generate",
                    hx_post="/generate",
                    hx_target="#response",
                    hx_swap="outerHTML",
                    hx_indicator=".chat-card",
                ),
                hx_post="/generate",
                hx_target="#response",
                hx_swap="outerHTML",
            ),
            response_box(),
            cls="chat-card",
        ),
    )


@rt("/generate")
def post(prompt: str):
    if not prompt.strip():
        return response_box("Please enter a prompt.", placeholder=False)

    result = llm.create_chat_completion(
        messages=[{"role": "user", "content": prompt.strip()}],
        max_tokens=512,
    )
    text = result["choices"][0]["message"]["content"]
    return response_box(text, placeholder=False)


@rt("/health")
def get():
    return "ok"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5001)
