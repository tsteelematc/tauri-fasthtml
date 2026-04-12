"""Native Agents — local LLM chat app served as the UI for the Tauri desktop shell."""

import asyncio
import json
import subprocess
import sys
import threading
from pathlib import Path

from fasthtml.common import *
from llama_cpp import Llama
from playwright.async_api import async_playwright

MODEL_PATH = Path(__file__).parent.parent / "models" / "qwen2.5-3b-instruct-q4_k_m.gguf"

# Lazy-loaded so uvicorn can start and serve /health immediately
_llm: Llama | None = None
_llm_lock = threading.Lock()
_llm_ready = False


def _get_llm() -> Llama:
    global _llm, _llm_ready
    with _llm_lock:
        if _llm is None:
            print(f"Loading model from {MODEL_PATH}...", flush=True)
            _llm = Llama(model_path=str(MODEL_PATH), n_ctx=4096, verbose=False)
            _llm_ready = True
            print("Model loaded.", flush=True)
    return _llm


def _preload_model() -> None:
    """Background thread: load the model so the first request doesn't hang."""
    try:
        _get_llm()
    except Exception as exc:
        print(f"Model preload failed: {exc}", flush=True)


# Playwright browser — kept alive so windows stay open
_playwright = None
_browser = None
_pages: list = []  # keep page refs alive so they aren't GC'd and closed

# Tool definitions for llama-cpp function calling
TOOLS = [{
    "type": "function",
    "function": {
        "name": "star_trek_lookup",
        "description": "Search Bing for Star Trek information and open the results in a browser window.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The Star Trek topic to search for.",
                }
            },
            "required": ["query"],
        },
    },
}]

_STAR_TREK_KEYWORDS = {
    "star trek", "kirk", "spock", "picard", "data", "scotty", "uhura", "worf",
    "riker", "troi", "crusher", "la forge", "geordi", "janeway", "seven of nine",
    "enterprise", "voyager", "defiant", "deep space", "next generation",
    "tng", "ds9", "tos", "borg", "klingon", "vulcan", "romulan", "ferengi",
    "cardassian", "bajoran", "holodeck", "starfleet", "warp", "transporter",
    "tribble", "q continuum",
}


def _is_star_trek(prompt: str) -> bool:
    lower = prompt.lower()
    return any(kw in lower for kw in _STAR_TREK_KEYWORDS)


async def _ensure_browser():
    global _playwright, _browser
    if _browser is None or not _browser.is_connected():
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=False)
    return _browser


async def _web_search(query: str) -> str:
    url = f"https://www.bing.com/search?q={query}"
    try:
        browser = await _ensure_browser()
        page = await browser.new_page()
        _pages.append(page)  # prevent GC so the window stays open
        await page.goto(url)
        return f"Opened Bing search for: {query}"
    except Exception as playwright_err:
        print(f"Playwright failed ({playwright_err}), falling back to system browser", flush=True)
        # Fall back to system browser (open on macOS, start on Windows)
        if sys.platform == "darwin":
            subprocess.Popen(["open", url])
        elif sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", "start", url], shell=False)
        else:
            subprocess.Popen(["xdg-open", url])
        return f"Opened Bing search for: {query}"


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
            .tool-indicator {
                margin-top: 0.75rem; padding: 0.5rem 0.75rem;
                background: rgba(255,255,255,0.1); border-radius: 8px;
                font-size: 0.85rem; color: rgba(255,255,255,0.7);
            }
            .placeholder { color: rgba(255,255,255,0.5); font-style: italic; }
            .htmx-indicator { opacity: 0.6; }
        """)
    ]
)


def response_box(text: str = "", tool_info: str = "", placeholder: bool = True):
    parts = []
    if tool_info:
        parts.append(Div(f"🔧 {tool_info}", cls="tool-indicator"))
    if placeholder and not text:
        parts.append(Div(Span("Response will appear here...", cls="placeholder"), cls="response-box"))
    else:
        parts.append(Div(text, cls="response-box"))
    return Div(*parts, id="response")


@rt("/")
def get():
    return Titled(
        "Native Agents",
        Div(
            H1("🤖 Native Agents"),
            Form(
                Textarea(
                    name="prompt",
                    placeholder='Try: "search for weather forecast"',
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
async def post(prompt: str):
    if not prompt.strip():
        return response_box("Please enter a prompt.", placeholder=False)

    if not _llm_ready:
        return response_box("⏳ Model is still loading, please try again in a moment.", placeholder=False)

    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant. Answer questions directly and concisely.",
        },
        {"role": "user", "content": prompt.strip()},
    ]
    tool_info = ""

    # Only offer tools when the prompt is Star Trek-related — deterministic routing
    active_tools = TOOLS if _is_star_trek(prompt) else []

    # First LLM call — may produce a tool call or a direct answer
    result = _get_llm().create_chat_completion(
        messages=messages,
        tools=active_tools if active_tools else None,
        tool_choice="auto" if active_tools else None,
        max_tokens=512,
    )

    choice = result["choices"][0]
    message = choice["message"]
    content = message.get("content") or ""

    # Check structured tool_calls first, then fall back to parsing raw <tool_call> tags
    tool_calls = message.get("tool_calls")
    parsed_call = None

    if not tool_calls and "<tool_call>" in content:
        # Qwen models emit tool calls as: <tool_call>{{"name":...,"arguments":...}}</tool_call>
        import re
        match = re.search(r"<tool_call>\s*(\{.*\})\s*</tool_call>", content, re.DOTALL)
        if match:
            try:
                raw = match.group(1).replace("{{", "{").replace("}}", "}")
                call_data = json.loads(raw)
                parsed_call = {
                    "name": call_data.get("name", ""),
                    "arguments": call_data.get("arguments", {}),
                }
            except json.JSONDecodeError:
                pass

    if tool_calls:
        tc = tool_calls[0]
        fn_name = tc["function"]["name"]
        fn_args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
        tc_id = tc.get("id", "call_0")
    elif parsed_call:
        fn_name = parsed_call["name"]
        fn_args = parsed_call["arguments"] if isinstance(parsed_call["arguments"], dict) else json.loads(parsed_call["arguments"])
        tc_id = "call_0"
    else:
        fn_name = None

    if fn_name:
        tool_info = f"Using tool: {fn_name}({json.dumps(fn_args)})"

        try:
            if fn_name == "star_trek_lookup":
                tool_result = await _web_search(fn_args.get("query", ""))
            else:
                tool_result = f"Unknown tool: {fn_name}"
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"Tool error: {error_detail}", flush=True)
            tool_result = f"Tool error: {e}"
            return response_box(f"Tool error: {e}\n\n{error_detail}", tool_info=tool_info, placeholder=False)

        # Feed tool result back to model for a final response
        messages.append({"role": "assistant", "content": None, "tool_calls": [{"id": tc_id, "type": "function", "function": {"name": fn_name, "arguments": json.dumps(fn_args)}}]})
        messages.append({
            "role": "tool",
            "tool_call_id": tc_id,
            "content": tool_result,
        })

        try:
            follow_up = _get_llm().create_chat_completion(
                messages=messages,
                max_tokens=512,
            )
            text = follow_up["choices"][0]["message"]["content"]
        except Exception:
            # If the follow-up LLM call fails, just show the tool result
            text = tool_result
    else:
        text = message.get("content", "")

    return response_box(text or "Done.", tool_info=tool_info, placeholder=False)


@rt("/health")
def get():
    return "ok"


if __name__ == "__main__":
    import uvicorn
    threading.Thread(target=_preload_model, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=5001)
