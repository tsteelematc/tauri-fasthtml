"""Native Agents — local LLM chat app served as the UI for the Tauri desktop shell."""

import asyncio
import json
import subprocess
import sys
import threading
from pathlib import Path

from platformdirs import user_data_dir
from fasthtml.common import *
from llama_cpp import Llama
from playwright.async_api import async_playwright
from theme_toggle import get_theme, set_dark_theme, set_light_theme, toggle_theme

MODEL_PATH = Path(__file__).parent.parent / "models" / "qwen2.5-3b-instruct-q4_k_m.gguf"

_SETTINGS_PATH = Path(user_data_dir("NativeAgents", "NativeAgents")) / "settings.json"


def _load_dark_mode() -> bool:
    try:
        data = json.loads(_SETTINGS_PATH.read_text())
        return bool(data.get("dark_mode", True))
    except Exception:
        return True


def _save_dark_mode(value: bool) -> None:
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(json.dumps({"dark_mode": value}))
    except Exception:
        pass


_dark_mode: bool = _load_dark_mode()

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
_STAR_TREK_TOOL = {
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
}

_APPEARANCE_TOOL = {
    "type": "function",
    "function": {
        "name": "set_appearance",
        "description": "Set the OS appearance (dark or light mode) or toggle it. Works on Windows and macOS.",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["dark", "light", "toggle", "get"],
                    "description": "The appearance action: 'dark' sets dark mode, 'light' sets light mode, 'toggle' switches between them, 'get' returns the current setting.",
                }
            },
            "required": ["mode"],
        },
    },
}

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


def _make_css(dark: bool) -> str:
    if dark:
        bg = "#111113"
        body_color = "#c8c8cc"
        shell_header_color = "#6e6e76"
        accent = "#34d399"
        input_bg = "#1a1a1e"
        input_color = "#e0e0e4"
        input_border = "#2a2a30"
        placeholder = "#4a4a52"
        scrollbar_thumb = "#2a2a30"
        empty_state = "#4a4a52"
        exchange_border = "#1e1e24"
        tool_tag_bg = "#1e1e24"
        tool_tag_border = "#2a2a30"
        thinking_color = "#6e6e76"
    else:
        bg = "#f5f5f7"
        body_color = "#1d1d1f"
        shell_header_color = "#6e6e73"
        accent = "#059669"
        input_bg = "#ffffff"
        input_color = "#1d1d1f"
        input_border = "#d1d1d6"
        placeholder = "#aeaeb2"
        scrollbar_thumb = "#c7c7cc"
        empty_state = "#8e8e93"
        exchange_border = "#e5e5ea"
        tool_tag_bg = "#f0f0f5"
        tool_tag_border = "#d1d1d6"
        thinking_color = "#8e8e93"

    return f"""
        *{{box-sizing:border-box;margin:0;padding:0}}
        html{{height:100%;background:{bg}}}
        body{{
            font-family:'SF Mono','Cascadia Code','Fira Code','Consolas',monospace;
            background:{bg};
            color:{body_color};
            display:flex;flex-direction:column;
            min-height:100%;
        }}
        body::before{{
            content:'';display:block;height:2px;flex-shrink:0;
            background:linear-gradient(90deg,#10b981 0%,#06b6d4 50%,#10b981 100%);
        }}
        .shell{{
            flex:1;display:flex;flex-direction:column;
            padding:1.25rem 1.5rem 1rem;
            max-width:56rem;width:100%;
        }}
        @media(min-width:64rem){{.shell{{padding:1.5rem 2rem 1rem}}}}
        .shell-header{{
            display:flex;align-items:center;gap:0.5rem;
            margin-bottom:1.25rem;
            font-size:0.8rem;color:{shell_header_color};
            user-select:none;
        }}
        .shell-header .accent{{color:{accent}}}
        .shell-header .status-ready{{color:#3ddc84}}
        .shell-header .status-loading{{color:#f5a623}}
        .shell-header .theme-toggle{{
            color:{shell_header_color};
            text-decoration:underline;
            text-underline-offset:2px;
            cursor:pointer;
        }}
        .shell-header .theme-toggle:hover{{color:{accent}}}
        .cmd-input{{
            display:flex;gap:0.5rem;align-items:flex-start;
            margin-bottom:1rem;
        }}
        .cmd-input textarea{{
            flex:1;
            background:{input_bg};color:{input_color};
            border:1px solid {input_border};border-radius:6px;
            padding:0.5rem 0.75rem;
            font-family:inherit;font-size:0.9rem;
            resize:none;outline:none;
            min-height:2.25rem;max-height:10rem;
            line-height:1.5;
            transition:border-color .15s;
        }}
        .cmd-input textarea::placeholder{{color:{placeholder}}}
        .cmd-input textarea:focus{{border-color:#10b981}}
        .cmd-input button{{
            background:#10b981;color:#fff;
            border:none;border-radius:6px;
            padding:0 1rem;
            font-family:inherit;font-size:0.85rem;
            cursor:pointer;white-space:nowrap;
            transition:background .15s;
            height:2.25rem;flex-shrink:0;
            line-height:2.25rem;
        }}
        .cmd-input button:hover{{background:#059669}}
        .cmd-input button:active{{background:#047857}}
        #output-log{{
            flex:1;overflow-y:auto;
            padding:0.5rem 0;
            font-size:0.88rem;line-height:1.7;
        }}
        #output-log::-webkit-scrollbar{{width:4px}}
        #output-log::-webkit-scrollbar-thumb{{background:{scrollbar_thumb};border-radius:2px}}
        .empty-state{{color:{empty_state};font-style:italic;font-size:0.85rem}}
        .exchange{{
            padding:0.75rem 0;
            border-bottom:1px solid {exchange_border};
        }}
        .exchange:last-child{{border-bottom:none}}
        .exchange .user-prompt{{
            color:{shell_header_color};font-size:0.8rem;margin-bottom:0.4rem;
            display:flex;align-items:baseline;gap:0.4rem;
        }}
        .exchange .user-prompt .label{{color:#10b981}}
        .exchange .agent-response{{
            white-space:pre-wrap;word-break:break-word;
            color:{body_color};
        }}
        .exchange .tool-tag{{
            display:block;
            background:{tool_tag_bg};border:1px solid {tool_tag_border};border-radius:4px;
            padding:0.2rem 0.5rem;margin-bottom:0.5rem;
            font-size:0.78rem;color:#53a8e2;
            width:fit-content;
        }}
        .thinking{{
            color:{thinking_color};display:flex;align-items:center;gap:0.4rem;
            padding:0.5rem 0;font-size:0.88rem;
        }}
        .thinking .dots span{{
            display:inline-block;width:4px;height:4px;
            background:#10b981;border-radius:50%;
            animation:blink 1.4s infinite both;
        }}
        .thinking .dots span:nth-child(2){{animation-delay:.2s}}
        .thinking .dots span:nth-child(3){{animation-delay:.4s}}
        @keyframes blink{{
            0%,80%,100%{{opacity:.25}}
            40%{{opacity:1}}
        }}
        .htmx-indicator{{display:none}}
        .htmx-request .htmx-indicator{{display:flex}}
        .htmx-request .cmd-input button{{opacity:.5;pointer-events:none}}
    """


app, rt = fast_app(
    hdrs=[
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
            // remove placeholder on first response
            document.addEventListener('htmx:afterSettle', () => {
                const log = document.getElementById('output-log');
                if(log){
                    const empty = log.querySelector('.empty-state');
                    if(empty) empty.remove();
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
    toggle_label = "toggle light" if _dark_mode else "toggle dark"
    return Div(
        Span("native-agents", cls="accent"),
        Span(" — local model · "),
        _status_span(),
        Span(" · "),
        A(toggle_label, href="/toggle-app-theme", cls="theme-toggle"),
        id="shell-header",
        cls="shell-header",
        hx_get="/status",
        hx_trigger="every 5s" if not _llm_ready else None,
        hx_swap="outerHTML",
    )


@rt("/toggle-app-theme")
def get():
    global _dark_mode
    _dark_mode = not _dark_mode
    _save_dark_mode(_dark_mode)
    from starlette.responses import RedirectResponse as _Redirect
    return _Redirect("/", status_code=302)


@rt("/")
def get():
    toggle_label = "toggle light" if _dark_mode else "toggle dark"
    return (
        Title("Native Agents"),
        Style(_make_css(_dark_mode)),
        Div(
            Div(
                Span("native-agents", cls="accent"),
                Span(" — local model · "),
                _status_span(),
                Span(" · "),
                A(toggle_label, href="/toggle-app-theme", cls="theme-toggle"),
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
                hx_swap="afterbegin",
            ),
            Div(
                Span("waiting for response…", cls="empty-state"),
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

    # Appearance tool is always available; Star Trek tool is keyword-gated
    active_tools = [_APPEARANCE_TOOL]
    if _is_star_trek(prompt):
        active_tools.append(_STAR_TREK_TOOL)

    # First LLM call — may produce a tool call or a direct answer
    result = _get_llm().create_chat_completion(
        messages=messages,
        tools=active_tools,
        tool_choice="auto",
        max_tokens=512,
    )

    choice = result["choices"][0]
    message = choice["message"]
    content = message.get("content") or ""

    # Check structured tool_calls first, then fall back to parsing raw text
    tool_calls = message.get("tool_calls")
    parsed_call = None

    if not tool_calls and content.strip():
        import re
        # Try <tool_call> wrapped JSON first
        match = re.search(r"<tool_call>\s*(\{.*\})\s*(?:</tool_call>|$)", content, re.DOTALL)
        # Fall back to bare JSON with a "name" key (model sometimes omits tags)
        if not match:
            match = re.search(r'(\{\s*"name"\s*:.*\})', content, re.DOTALL)
        if match:
            try:
                raw = match.group(1).replace("{{", "{").replace("}}", "}")
                call_data = json.loads(raw)
                if "name" in call_data:
                    parsed_call = {
                        "name": call_data["name"],
                        "arguments": call_data.get("arguments", {}),
                    }
            except json.JSONDecodeError:
                pass


    fn_name = None
    fn_args = {}
    tc_id = "call_0"

    if tool_calls:
        try:
            tc = tool_calls[0]
            fn_name = tc["function"]["name"]
            fn_args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
            tc_id = tc.get("id", "call_0")
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            print(f"[DEBUG] structured tool_calls parse failed: {e}", flush=True)
            fn_name = None

    if not fn_name and parsed_call:
        fn_name = parsed_call["name"]
        fn_args = parsed_call["arguments"] if isinstance(parsed_call["arguments"], dict) else json.loads(parsed_call["arguments"])
        tc_id = "call_0"

    # Deterministic fallback: if _is_star_trek matched but model didn't call the tool,
    # force the call using the original prompt as the query
    if not fn_name and _is_star_trek(prompt):
        fn_name = "star_trek_lookup"
        fn_args = {"query": prompt.strip()}
        tc_id = "call_0"

    if fn_name:
        tool_info = f"{fn_name}({json.dumps(fn_args)})"

        try:
            if fn_name == "star_trek_lookup":
                tool_result = await _web_search(fn_args.get("query", ""))
            elif fn_name == "set_appearance":
                mode = fn_args.get("mode", "toggle")
                if mode == "dark":
                    tool_result = set_dark_theme()
                elif mode == "light":
                    tool_result = set_light_theme()
                elif mode == "toggle":
                    tool_result = toggle_theme()
                elif mode == "get":
                    tool_result = get_theme()
                else:
                    tool_result = f"Unknown appearance mode: {mode}"
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
        # Strip any unparsed <tool_call> tags that leaked through
        import re
        text = re.sub(r"</?tool_call>", "", text).strip()

    return _exchange(text or "done.", prompt=prompt.strip(), tool_info=tool_info)


@rt("/health")
def get():
    return "ok"


if __name__ == "__main__":
    import uvicorn
    threading.Thread(target=_preload_model, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=5001)
