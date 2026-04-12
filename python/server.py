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
            *{box-sizing:border-box;margin:0;padding:0}
            html,body{height:100%}
            body{
                font-family:'SF Mono','Cascadia Code','Fira Code','Consolas',monospace;
                background:#111113;
                color:#c8c8cc;
                display:flex;flex-direction:column;
                min-height:100vh;
            }
            /* subtle gradient bar at top */
            body::before{
                content:'';display:block;height:2px;flex-shrink:0;
                background:linear-gradient(90deg,#6e56cf 0%,#53a8e2 50%,#6e56cf 100%);
            }
            .shell{
                flex:1;display:flex;flex-direction:column;
                padding:1.25rem 1.5rem 1rem;
                max-width:56rem;width:100%;
            }
            @media(min-width:64rem){.shell{padding:1.5rem 2rem 1rem}}
            /* header — live-updated via /status */
            .shell-header{
                display:flex;align-items:center;gap:0.5rem;
                margin-bottom:1.25rem;
                font-size:0.8rem;color:#6e6e76;
                user-select:none;
            }
            .shell-header .accent{color:#8b8bf5}
            .shell-header .status-ready{color:#3ddc84}
            .shell-header .status-loading{color:#f5a623}
            /* command input area */
            .cmd-input{
                display:flex;gap:0.5rem;align-items:flex-start;
                margin-bottom:1rem;
            }
            .cmd-input textarea{
                flex:1;
                background:#1a1a1e;color:#e0e0e4;
                border:1px solid #2a2a30;border-radius:6px;
                padding:0.5rem 0.75rem;
                font-family:inherit;font-size:0.9rem;
                resize:none;outline:none;
                min-height:2.25rem;max-height:10rem;
                line-height:1.5;
                transition:border-color .15s;
            }
            .cmd-input textarea::placeholder{color:#4a4a52}
            .cmd-input textarea:focus{border-color:#6e56cf}
            .cmd-input button{
                background:#6e56cf;color:#fff;
                border:none;border-radius:6px;
                padding:0 1rem;
                font-family:inherit;font-size:0.85rem;
                cursor:pointer;white-space:nowrap;
                transition:background .15s;
                height:2.25rem;flex-shrink:0;
                line-height:2.25rem;
            }
            .cmd-input button:hover{background:#7c6ad4}
            .cmd-input button:active{background:#5b45b0}
            /* output region */
            #output-log{
                flex:1;overflow-y:auto;
                padding:0.5rem 0;
                font-size:0.88rem;line-height:1.7;
            }
            #output-log::-webkit-scrollbar{width:4px}
            #output-log::-webkit-scrollbar-thumb{background:#2a2a30;border-radius:2px}
            .empty-state{color:#4a4a52;font-style:italic;font-size:0.85rem}
            /* individual exchange block */
            .exchange{
                padding:0.75rem 0;
                border-bottom:1px solid #1e1e24;
            }
            .exchange:last-child{border-bottom:none}
            .exchange .user-prompt{
                color:#6e6e76;font-size:0.8rem;margin-bottom:0.4rem;
                display:flex;align-items:baseline;gap:0.4rem;
            }
            .exchange .user-prompt .label{color:#6e56cf}
            .exchange .agent-response{
                white-space:pre-wrap;word-break:break-word;
                color:#c8c8cc;
            }
            .exchange .tool-tag{
                display:block;
                background:#1e1e24;border:1px solid #2a2a30;border-radius:4px;
                padding:0.2rem 0.5rem;margin-bottom:0.5rem;
                font-size:0.78rem;color:#53a8e2;
                width:fit-content;
            }
            /* thinking indicator */
            .thinking{
                color:#6e6e76;display:flex;align-items:center;gap:0.4rem;
                padding:0.5rem 0;font-size:0.88rem;
            }
            .thinking .dots span{
                display:inline-block;width:4px;height:4px;
                background:#6e56cf;border-radius:50%;
                animation:blink 1.4s infinite both;
            }
            .thinking .dots span:nth-child(2){animation-delay:.2s}
            .thinking .dots span:nth-child(3){animation-delay:.4s}
            @keyframes blink{
                0%,80%,100%{opacity:.25}
                40%{opacity:1}
            }
            .htmx-indicator{display:none}
            .htmx-request .htmx-indicator{display:flex}
            .htmx-request .cmd-input button{opacity:.5;pointer-events:none}
        """),
        # auto-resize textarea, submit on Enter, clear after submit
        Script("""
            document.addEventListener('input', e => {
                if(e.target.matches('.cmd-input textarea')){
                    e.target.style.height='auto';
                    e.target.style.height=Math.min(e.target.scrollHeight,160)+'px';
                }
            });
            document.addEventListener('keydown', e => {
                if(e.target.matches('.cmd-input textarea') && e.key==='Enter' && !e.shiftKey){
                    e.preventDefault();
                    htmx.trigger(e.target.closest('form'), 'submit');
                }
            });
            // clear textarea after successful htmx request
            document.addEventListener('htmx:afterRequest', e => {
                if(!e.detail.successful) return;
                const ta = e.target.querySelector('textarea[name=prompt]');
                if(ta){ ta.value=''; ta.style.height='auto'; }
            });
            // auto-scroll output log to bottom on new content
            document.addEventListener('htmx:afterSettle', () => {
                const log = document.getElementById('output-log');
                if(log){
                    // remove the empty-state placeholder once we have real content
                    const empty = log.querySelector('.empty-state');
                    if(empty) empty.remove();
                    log.scrollTop = log.scrollHeight;
                }
            });
        """),
    ]
)


def _thinking_indicator():
    """Animated 'Thinking' shown while HTMX request is in-flight."""
    return Div(
        Span("thinking"),
        Span(Span(), Span(), Span(), cls="dots"),
        cls="thinking htmx-indicator",
    )


def _status_span():
    """Model status badge for the header."""
    if _llm_ready:
        return Span("ready", cls="status-ready")
    return Span("loading model…", cls="status-loading")


def _exchange(text: str, prompt: str = "", tool_info: str = ""):
    """A single prompt→response exchange block in the output log."""
    parts = []
    if prompt:
        parts.append(
            Div(Span("›", cls="label"), Span(f" {prompt}"), cls="user-prompt")
        )
    if tool_info:
        parts.append(Div(f"⚡ {tool_info}", cls="tool-tag"))
    parts.append(Div(text, cls="agent-response"))
    return Div(*parts, cls="exchange")


@rt("/status")
def get():
    """Returns just the header content — polled by hx-trigger."""
    return Div(
        Span("native-agents", cls="accent"),
        Span(" — local model · "),
        _status_span(),
        id="shell-header",
        cls="shell-header",
        hx_get="/status",
        hx_trigger="every 5s" if not _llm_ready else None,
        hx_swap="outerHTML",
    )


@rt("/")
def get():
    return (
        Title("Native Agents"),
        Div(
            Div(
                Span("native-agents", cls="accent"),
                Span(" — local model · "),
                _status_span(),
                id="shell-header",
                cls="shell-header",
                hx_get="/status",
                hx_trigger="every 5s" if not _llm_ready else None,
                hx_swap="outerHTML",
            ),
            Form(
                Div(
                    Textarea(
                        name="prompt",
                        placeholder="ask anything…",
                        rows=1,
                        autofocus=True,
                    ),
                    Button("run"),
                    cls="cmd-input",
                ),
                _thinking_indicator(),
                hx_post="/generate",
                hx_target="#output-log",
                hx_swap="beforeend",
            ),
            Div(
                Span("waiting for input…", cls="empty-state"),
                id="output-log",
            ),
            cls="shell",
        ),
    )


@rt("/generate")
async def post(prompt: str):
    if not prompt.strip():
        return ""

    if not _llm_ready:
        return _exchange("⏳ model is still loading — try again in a moment.", prompt=prompt.strip())

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
        tool_info = f"{fn_name}({json.dumps(fn_args)})"

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
            return _exchange(
                f"tool error: {e}\n\n{error_detail}",
                prompt=prompt.strip(),
                tool_info=tool_info,
            )

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

    return _exchange(text or "done.", prompt=prompt.strip(), tool_info=tool_info)


@rt("/health")
def get():
    return "ok"


if __name__ == "__main__":
    import uvicorn
    threading.Thread(target=_preload_model, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=5001)
