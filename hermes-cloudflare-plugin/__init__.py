"""
Cloudflare Browser Rendering Plugin
====================================

Provides tools for Cloudflare's Browser Rendering REST API:
  - /crawl   – async website crawling with pagination
  - /scrape  – CSS-selector-based element extraction
  - /markdown – page-to-markdown conversion
  - /json    – AI-powered structured data extraction
  - /links   – link discovery
  - /content – full rendered HTML
  - /screenshot – page screenshots
  - /pdf     – page-to-PDF rendering

Requires:
  CLOUDFLARE_API_TOKEN  – API token with "Browser Rendering - Edit" permission
  CLOUDFLARE_ACCOUNT_ID – Your Cloudflare account ID
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = "https://api.cloudflare.com/client/v4/accounts"


def _check_available() -> bool:
    return bool(
        os.getenv("CLOUDFLARE_API_TOKEN") and os.getenv("CLOUDFLARE_ACCOUNT_ID")
    )


def _api_url(endpoint: str) -> str:
    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    return f"{_BASE}/{account_id}/browser-rendering/{endpoint}"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}",
        "Content-Type": "application/json",
    }


def _post(endpoint: str, payload: dict, *, timeout: float = 120.0) -> dict:
    """POST to a Cloudflare Browser Rendering endpoint and return the JSON response."""
    if httpx is None:
        return {"error": "httpx is not installed. Run: pip install httpx"}
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(_api_url(endpoint), headers=_headers(), json=payload)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            return resp.json()
        # Binary responses (screenshot, pdf) – return base64
        import base64

        return {
            "success": True,
            "result_base64": base64.b64encode(resp.content).decode(),
        }


def _get(
    endpoint: str, params: Optional[dict] = None, *, timeout: float = 60.0
) -> dict:
    if httpx is None:
        return {"error": "httpx is not installed. Run: pip install httpx"}
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(_api_url(endpoint), headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


def _delete(endpoint: str, *, timeout: float = 30.0) -> dict:
    if httpx is None:
        return {"error": "httpx is not installed. Run: pip install httpx"}
    with httpx.Client(timeout=timeout) as client:
        resp = client.delete(_api_url(endpoint), headers=_headers())
        resp.raise_for_status()
        return resp.json()


def _build_common_opts(args: dict) -> dict:
    """Extract common optional parameters shared across endpoints."""
    opts: Dict[str, Any] = {}
    if args.get("wait_until"):
        opts["gotoOptions"] = {"waitUntil": args["wait_until"]}
    if args.get("user_agent"):
        opts["userAgent"] = args["user_agent"]
    if args.get("wait_for_selector"):
        opts["waitForSelector"] = {"selector": args["wait_for_selector"]}
    if args.get("reject_resource_types"):
        opts["rejectResourceTypes"] = args["reject_resource_types"]
    if args.get("extra_headers"):
        opts["setExtraHTTPHeaders"] = args["extra_headers"]
    if args.get("cookies"):
        opts["cookies"] = args["cookies"]
    return opts


def _limit_response_size(text: str, max_chars: int = 50000) -> str:
    """Truncate large responses to prevent context overflow."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    head = text[:half]
    tail = text[-half:]
    omitted = len(text) - max_chars
    notice = (
        f"\n... [TRUNCATED: {len(text):,} chars total, {omitted:,} chars omitted] ...\n"
        f"[TIP: Use cf_scrape with specific selectors for targeted extraction]\n"
    )
    return head + notice + tail


def handle_cf_crawl(args: dict, **kw) -> str:
    """Start an async crawl job or check status / cancel an existing one."""
    action = args.get("action", "start")

    if action == "start":
        payload: Dict[str, Any] = {"url": args["url"]}
        if args.get("limit"):
            payload["limit"] = args["limit"]
        if args.get("depth"):
            payload["depth"] = args["depth"]
        if args.get("formats"):
            payload["formats"] = args["formats"]
        if args.get("render") is not None:
            payload["render"] = args["render"]
        if args.get("source"):
            payload["source"] = args["source"]
        if args.get("include_patterns"):
            payload.setdefault("options", {})["includePatterns"] = args[
                "include_patterns"
            ]
        if args.get("exclude_patterns"):
            payload.setdefault("options", {})["excludePatterns"] = args[
                "exclude_patterns"
            ]
        if args.get("include_subdomains"):
            payload.setdefault("options", {})["includeSubdomains"] = args[
                "include_subdomains"
            ]
        payload.update(_build_common_opts(args))
        result = _post("crawl", payload, timeout=120.0)
        return _limit_response_size(json.dumps(result, indent=2))

    elif action == "status":
        job_id = args.get("job_id", "")
        params: Dict[str, Any] = {}
        if args.get("limit"):
            params["limit"] = args["limit"]
        if args.get("cursor"):
            params["cursor"] = args["cursor"]
        if args.get("status_filter"):
            params["status"] = args["status_filter"]
        result = _get(f"crawl/{job_id}", params=params)
        return _limit_response_size(json.dumps(result, indent=2))

    elif action == "cancel":
        job_id = args.get("job_id", "")
        result = _delete(f"crawl/{job_id}")
        return json.dumps(result, indent=2)

    return json.dumps({"error": f"Unknown action: {action}"})


def handle_cf_scrape(args: dict, **kw) -> str:
    """Scrape specific HTML elements from a page using CSS selectors."""
    selectors = args.get("selectors", [])
    elements = [{"selector": s} for s in selectors]
    payload: Dict[str, Any] = {"url": args["url"], "elements": elements}
    payload.update(_build_common_opts(args))
    result = _post("scrape", payload)
    return _limit_response_size(json.dumps(result, indent=2))


def handle_cf_markdown(args: dict, **kw) -> str:
    """Convert a web page to clean Markdown."""
    payload: Dict[str, Any] = {}
    if args.get("url"):
        payload["url"] = args["url"]
    if args.get("html"):
        payload["html"] = args["html"]
    payload.update(_build_common_opts(args))
    result = _post("markdown", payload)
    return _limit_response_size(json.dumps(result, indent=2))


def handle_cf_json_extract(args: dict, **kw) -> str:
    """Extract structured JSON data from a page using AI."""
    payload: Dict[str, Any] = {}
    if args.get("url"):
        payload["url"] = args["url"]
    if args.get("html"):
        payload["html"] = args["html"]
    if args.get("prompt"):
        payload["prompt"] = args["prompt"]
    if args.get("response_format"):
        payload["response_format"] = args["response_format"]
    payload.update(_build_common_opts(args))
    result = _post("json", payload)
    return json.dumps(result, indent=2)


def handle_cf_links(args: dict, **kw) -> str:
    """Extract all links from a web page."""
    payload: Dict[str, Any] = {"url": args["url"]}
    if args.get("visible_only"):
        payload["visibleLinksOnly"] = args["visible_only"]
    if args.get("exclude_external"):
        payload["excludeExternalLinks"] = args["exclude_external"]
    payload.update(_build_common_opts(args))
    result = _post("links", payload)
    return json.dumps(result, indent=2)


def handle_cf_content(args: dict, **kw) -> str:
    """Get fully rendered HTML content of a page (after JS execution)."""
    payload: Dict[str, Any] = {}
    if args.get("url"):
        payload["url"] = args["url"]
    if args.get("html"):
        payload["html"] = args["html"]
    payload.update(_build_common_opts(args))
    result = _post("content", payload)
    return _limit_response_size(json.dumps(result, indent=2))


def handle_cf_screenshot(args: dict, **kw) -> str:
    """Take a screenshot of a web page. Returns base64-encoded image."""
    payload: Dict[str, Any] = {"url": args["url"]}
    screenshot_opts: Dict[str, Any] = {}
    if args.get("full_page"):
        screenshot_opts["fullPage"] = args["full_page"]
    if args.get("image_type"):
        screenshot_opts["type"] = args["image_type"]
    if args.get("quality"):
        screenshot_opts["quality"] = args["quality"]
    if args.get("omit_background"):
        screenshot_opts["omitBackground"] = args["omit_background"]
    if screenshot_opts:
        payload["screenshotOptions"] = screenshot_opts
    if args.get("viewport"):
        payload["viewport"] = args["viewport"]
    if args.get("selector"):
        payload["selector"] = args["selector"]
    payload.update(_build_common_opts(args))
    result = _post("screenshot", payload)
    return json.dumps(result, indent=2)


def handle_cf_pdf(args: dict, **kw) -> str:
    """Render a web page as PDF. Returns base64-encoded PDF."""
    payload: Dict[str, Any] = {"url": args["url"]}
    if args.get("pdf_options"):
        payload["pdfOptions"] = args["pdf_options"]
    if args.get("viewport"):
        payload["viewport"] = args["viewport"]
    if args.get("header_template"):
        payload["headerTemplate"] = args["header_template"]
    if args.get("footer_template"):
        payload["footerTemplate"] = args["footer_template"]
    payload.update(_build_common_opts(args))
    result = _post("pdf", payload)
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "cf_crawl",
        "schema": {
            "name": "cf_crawl",
            "description": (
                "Cloudflare Browser Rendering: crawl an entire website asynchronously. "
                "Use action='start' to begin a crawl (returns a job_id), "
                "action='status' to poll results (pass job_id), "
                "action='cancel' to stop a running job. "
                "Supports depth/limit controls, format selection (html/markdown/json), "
                "include/exclude URL patterns, sitemap discovery, and incremental crawling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "status", "cancel"],
                        "description": "start=begin crawl, status=poll results, cancel=stop job",
                    },
                    "url": {
                        "type": "string",
                        "description": "Starting URL to crawl (required for action=start)",
                    },
                    "job_id": {
                        "type": "string",
                        "description": "Job ID returned by start (required for status/cancel)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max pages to crawl (start) or max records to return (status). Default: 10",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Max link depth from starting URL",
                    },
                    "formats": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["html", "markdown", "json"],
                        },
                        "description": "Output formats. Default: ['html']",
                    },
                    "render": {
                        "type": "boolean",
                        "description": "Execute JS with headless browser. Set false for static HTML (faster)",
                    },
                    "source": {
                        "type": "string",
                        "enum": ["all", "sitemaps", "links"],
                        "description": "URL discovery source. Default: 'all'",
                    },
                    "include_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Wildcard patterns to include (e.g. '/blog/*')",
                    },
                    "exclude_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Wildcard patterns to exclude",
                    },
                    "include_subdomains": {
                        "type": "boolean",
                        "description": "Follow links to subdomains",
                    },
                    "cursor": {
                        "type": "string",
                        "description": "Pagination cursor for status polling",
                    },
                    "status_filter": {
                        "type": "string",
                        "enum": [
                            "queued",
                            "completed",
                            "disallowed",
                            "skipped",
                            "errored",
                            "cancelled",
                        ],
                        "description": "Filter results by page status",
                    },
                    "wait_until": {
                        "type": "string",
                        "enum": [
                            "networkidle0",
                            "networkidle2",
                            "load",
                            "domcontentloaded",
                        ],
                        "description": "Page load condition",
                    },
                    "user_agent": {
                        "type": "string",
                        "description": "Custom user-agent string",
                    },
                    "wait_for_selector": {
                        "type": "string",
                        "description": "CSS selector to wait for before processing",
                    },
                    "reject_resource_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Block resource types: image, media, font, stylesheet",
                    },
                },
                "required": ["action"],
            },
        },
        "handler": handle_cf_crawl,
        "description": "Crawl entire websites via Cloudflare Browser Rendering",
        "emoji": "🕷️",
    },
    {
        "name": "cf_scrape",
        "schema": {
            "name": "cf_scrape",
            "description": (
                "Cloudflare Browser Rendering: scrape specific HTML elements from a page "
                "using CSS selectors. Returns text, HTML, attributes, and element dimensions "
                "for each matched selector."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL of the page to scrape",
                    },
                    "selectors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "CSS selectors to extract (e.g. ['h1', '.price', '#main'])",
                    },
                    "wait_until": {
                        "type": "string",
                        "enum": [
                            "networkidle0",
                            "networkidle2",
                            "load",
                            "domcontentloaded",
                        ],
                        "description": "Page load condition (use networkidle0 for SPAs)",
                    },
                    "user_agent": {
                        "type": "string",
                        "description": "Custom user-agent string",
                    },
                    "wait_for_selector": {
                        "type": "string",
                        "description": "CSS selector to wait for before scraping",
                    },
                },
                "required": ["url", "selectors"],
            },
        },
        "handler": handle_cf_scrape,
        "description": "Scrape HTML elements from web pages with CSS selectors",
        "emoji": "🔍",
    },
    {
        "name": "cf_markdown",
        "schema": {
            "name": "cf_markdown",
            "description": (
                "Cloudflare Browser Rendering: convert a web page to clean Markdown. "
                "Renders the page with a headless browser first (handles JS-heavy sites), "
                "then produces cleaned Markdown suitable for summaries, diffs, or embeddings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to convert to Markdown",
                    },
                    "html": {
                        "type": "string",
                        "description": "Raw HTML to convert (alternative to url)",
                    },
                    "wait_until": {
                        "type": "string",
                        "enum": [
                            "networkidle0",
                            "networkidle2",
                            "load",
                            "domcontentloaded",
                        ],
                    },
                    "user_agent": {"type": "string"},
                    "wait_for_selector": {"type": "string"},
                    "reject_resource_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Block resource types to speed up rendering",
                    },
                },
                "required": [],
            },
        },
        "handler": handle_cf_markdown,
        "description": "Convert web pages to clean Markdown",
        "emoji": "📝",
    },
    {
        "name": "cf_json_extract",
        "schema": {
            "name": "cf_json_extract",
            "description": (
                "Cloudflare Browser Rendering: extract structured JSON data from a web page "
                "using AI (Workers AI with Llama 3.3 70B by default). Provide a natural language "
                "prompt and/or a JSON schema defining the expected output structure."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to extract data from",
                    },
                    "html": {
                        "type": "string",
                        "description": "Raw HTML (alternative to url)",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Natural language instruction for what to extract (e.g. 'Extract all product names and prices')",
                    },
                    "response_format": {
                        "type": "object",
                        "description": "JSON schema defining expected output structure",
                    },
                    "wait_until": {
                        "type": "string",
                        "enum": [
                            "networkidle0",
                            "networkidle2",
                            "load",
                            "domcontentloaded",
                        ],
                    },
                    "user_agent": {"type": "string"},
                    "wait_for_selector": {"type": "string"},
                },
                "required": [],
            },
        },
        "handler": handle_cf_json_extract,
        "description": "AI-powered structured data extraction from web pages",
        "emoji": "🤖",
    },
    {
        "name": "cf_links",
        "schema": {
            "name": "cf_links",
            "description": (
                "Cloudflare Browser Rendering: extract all links from a web page. "
                "Can filter to visible links only and exclude external domains."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to extract links from",
                    },
                    "visible_only": {
                        "type": "boolean",
                        "description": "Only return links visible to users. Default: false",
                    },
                    "exclude_external": {
                        "type": "boolean",
                        "description": "Exclude links to external domains. Default: false",
                    },
                    "wait_until": {
                        "type": "string",
                        "enum": [
                            "networkidle0",
                            "networkidle2",
                            "load",
                            "domcontentloaded",
                        ],
                    },
                    "user_agent": {"type": "string"},
                },
                "required": ["url"],
            },
        },
        "handler": handle_cf_links,
        "description": "Extract links from web pages",
        "emoji": "🔗",
    },
    {
        "name": "cf_content",
        "schema": {
            "name": "cf_content",
            "description": (
                "Cloudflare Browser Rendering: get the fully rendered HTML of a page "
                "after JavaScript execution. Returns complete HTML including head section."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to render"},
                    "html": {
                        "type": "string",
                        "description": "Raw HTML to render (alternative to url)",
                    },
                    "wait_until": {
                        "type": "string",
                        "enum": [
                            "networkidle0",
                            "networkidle2",
                            "load",
                            "domcontentloaded",
                        ],
                    },
                    "user_agent": {"type": "string"},
                    "wait_for_selector": {"type": "string"},
                    "reject_resource_types": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "extra_headers": {
                        "type": "object",
                        "description": "Additional HTTP headers to send",
                    },
                },
                "required": [],
            },
        },
        "handler": handle_cf_content,
        "description": "Get fully rendered HTML after JS execution",
        "emoji": "🌐",
    },
    {
        "name": "cf_screenshot",
        "schema": {
            "name": "cf_screenshot",
            "description": (
                "Cloudflare Browser Rendering: take a screenshot of a web page. "
                "Supports full-page capture, element-specific screenshots, viewport control, "
                "and multiple image formats. Returns base64-encoded image."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to screenshot"},
                    "full_page": {
                        "type": "boolean",
                        "description": "Capture the full scrollable page. Default: false",
                    },
                    "image_type": {
                        "type": "string",
                        "enum": ["png", "jpeg", "webp"],
                        "description": "Image format. Default: png",
                    },
                    "quality": {
                        "type": "integer",
                        "description": "JPEG/WebP quality (0-100)",
                    },
                    "omit_background": {
                        "type": "boolean",
                        "description": "Transparent background. Default: false",
                    },
                    "selector": {
                        "type": "string",
                        "description": "CSS selector to screenshot a specific element",
                    },
                    "viewport": {
                        "type": "object",
                        "properties": {
                            "width": {"type": "integer"},
                            "height": {"type": "integer"},
                            "deviceScaleFactor": {"type": "number"},
                        },
                        "description": "Viewport dimensions",
                    },
                    "wait_until": {
                        "type": "string",
                        "enum": [
                            "networkidle0",
                            "networkidle2",
                            "load",
                            "domcontentloaded",
                        ],
                    },
                    "user_agent": {"type": "string"},
                    "wait_for_selector": {"type": "string"},
                },
                "required": ["url"],
            },
        },
        "handler": handle_cf_screenshot,
        "description": "Take screenshots of web pages",
        "emoji": "📸",
    },
    {
        "name": "cf_pdf",
        "schema": {
            "name": "cf_pdf",
            "description": (
                "Cloudflare Browser Rendering: render a web page as a PDF document. "
                "Supports custom headers/footers, viewport control, and PDF options "
                "(format, margins, scale). Returns base64-encoded PDF."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to render as PDF"},
                    "pdf_options": {
                        "type": "object",
                        "description": "PDF settings: format, margins, scale, landscape, etc.",
                    },
                    "viewport": {
                        "type": "object",
                        "properties": {
                            "width": {"type": "integer"},
                            "height": {"type": "integer"},
                        },
                    },
                    "header_template": {
                        "type": "string",
                        "description": "HTML template for page headers",
                    },
                    "footer_template": {
                        "type": "string",
                        "description": "HTML template for page footers",
                    },
                    "wait_until": {
                        "type": "string",
                        "enum": [
                            "networkidle0",
                            "networkidle2",
                            "load",
                            "domcontentloaded",
                        ],
                    },
                    "user_agent": {"type": "string"},
                    "wait_for_selector": {"type": "string"},
                    "reject_resource_types": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["url"],
            },
        },
        "handler": handle_cf_pdf,
        "description": "Render web pages as PDF documents",
        "emoji": "📄",
    },
]


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def register(ctx):
    """Register all Cloudflare Browser Rendering tools."""
    for tool in TOOLS:
        ctx.register_tool(
            name=tool["name"],
            toolset="cloudflare",
            schema=tool["schema"],
            handler=tool["handler"],
            check_fn=_check_available,
            requires_env=["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"],
            is_async=False,
            description=tool["description"],
            emoji=tool["emoji"],
        )
    logger.info("Cloudflare Browser Rendering plugin: registered %d tools", len(TOOLS))
