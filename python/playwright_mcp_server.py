"""Playwright MCP server exposing a web_search tool over stdio transport."""

import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("playwright-browser")

# Persistent browser instance — stays open so the user can see results
_browser = None
_playwright = None


async def _ensure_browser():
    global _browser, _playwright
    if _browser is None or not _browser.is_connected():
        from playwright.async_api import async_playwright
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=False)
    return _browser


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="web_search",
            description="Open a visible browser window with Bing search results for the given query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to look up on Bing.",
                    }
                },
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "web_search":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    query = arguments.get("query", "")
    if not query:
        return [TextContent(type="text", text="Error: empty query")]

    browser = await _ensure_browser()
    page = await browser.new_page()
    url = f"https://www.bing.com/search?q={query}"
    await page.goto(url)

    return [TextContent(type="text", text=f"Opened Bing search for: {query}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
