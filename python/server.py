"""FastHTML counter app served as the UI for the Tauri desktop shell."""

from fasthtml.common import *

app, rt = fast_app(
    hdrs=[
        Style("""
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                display: flex; justify-content: center; align-items: center;
                min-height: 100vh; margin: 0;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .counter-card {
                background: rgba(255,255,255,0.15);
                backdrop-filter: blur(10px);
                border-radius: 20px; padding: 3rem;
                text-align: center; min-width: 300px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.2);
            }
            h1 { margin: 0 0 1rem; font-size: 1.5rem; font-weight: 300; }
            .count { font-size: 5rem; font-weight: 700; margin: 1rem 0; }
            .buttons { display: flex; gap: 1rem; justify-content: center; }
            button {
                font-size: 1.5rem; padding: 0.5rem 1.5rem;
                border: 2px solid white; border-radius: 12px;
                background: transparent; color: white; cursor: pointer;
                transition: all 0.2s;
            }
            button:hover { background: rgba(255,255,255,0.2); }
        """)
    ]
)

count = 0

def counter_display():
    return Div(
        H1("⚡ Tauri + FastHTML"),
        Div(str(count), cls="count", id="count"),
        Div(
            Button("−", hx_post="/decrement", hx_target="#counter", hx_swap="outerHTML"),
            Button("+", hx_post="/increment", hx_target="#counter", hx_swap="outerHTML"),
            cls="buttons"
        ),
        id="counter", cls="counter-card"
    )

@rt("/")
def get():
    return Titled("Counter", counter_display())

@rt("/increment")
def post():
    global count
    count += 1
    return counter_display()

@rt("/decrement")
def post():
    global count
    count -= 1
    return counter_display()

@rt("/health")
def get():
    return "ok"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5001)
