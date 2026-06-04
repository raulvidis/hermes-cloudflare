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

import base64
import atexit
import ipaddress
import json
import logging
import os
import threading
from typing import Any, Dict, Optional
from urllib.parse import urlparse

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = "https://api.cloudflare.com/client/v4/accounts"

# Module-level shared client for connection pooling. Created lazily on first
# use so we don't fail at import time if httpx is missing.
_shared_client: Any = None
_client_lock = threading.Lock()


def _cleanup_client() -> None:
    """Close the shared httpx client on process exit."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        _shared_client.close()


atexit.register(_cleanup_client)


def _get_client() -> Any:
    """Return a shared httpx.Client, creating one if needed.

    Per-request timeout is passed to the individual .request() call rather
    than the constructor so the same client (and its connection pool) can be
    reused across requests with different timeouts.
    """
    global _shared_client
    if httpx is None:
        raise RuntimeError("httpx is not installed. Run: pip install httpx")
    if _shared_client is None or _shared_client.is_closed:
        with _client_lock:
            if _shared_client is None or _shared_client.is_closed:
                _shared_client = httpx.Client(timeout=60.0)
    return _shared_client


def _check_available() -> bool:
    return bool(
        os.getenv("CLOUDFLARE_API_TOKEN") and os.getenv("CLOUDFLARE_ACCOUNT_ID")
    )


def _api_url(endpoint: str) -> str:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not account_id:
        raise ValueError("CLOUDFLARE_ACCOUNT_ID environment variable is not set")
    return f"{_BASE}/{account_id}/browser-rendering/{endpoint}"


def _headers() -> dict:
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token:
        raise ValueError("CLOUDFLARE_API_TOKEN environment variable is not set")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _validate_url(url: str) -> Optional[str]:
    """Validate that *url* is well-formed and targets a public host.

    Returns an error message string if invalid, or ``None`` if valid.
    Blocks private/internal IP ranges and requires http(s) scheme.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return f"URL is not parseable: {url!r}"

    if parsed.scheme not in ("http", "https"):
        return f"URL scheme must be http or https, got {parsed.scheme!r}"

    hostname = parsed.hostname
    if not hostname:
        return f"URL is missing a hostname: {url!r}"

    # Block private/reserved IPs (10.x, 172.16-31.x, 192.168.x, 127.x,
    # 169.254.x, ::1, fc00::/7, etc.)
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return f"URL targets a private/internal address: {hostname}"
    except ValueError:
        pass  # hostname is a domain name, not an IP — that's fine

    return None


def _request(
    method: str,
    endpoint: str,
    *,
    timeout: float = 60.0,
    binary_ok: bool = False,
    **kwargs: Any,
) -> dict:
    """Send an HTTP request to a Cloudflare Browser Rendering endpoint.

    Args:
        method: HTTP method ('get', 'post', 'delete').
        endpoint: API endpoint path (e.g. 'crawl').
        timeout: Request timeout in seconds.
        binary_ok: If True, non-JSON responses are base64-encoded instead of
            causing an error.
        **kwargs: Forwarded to the httpx method (e.g. json=, params=).

    Returns:
        Parsed JSON dict, or an error dict on failure.
    """
    if httpx is None:
        return {"error": "httpx is not installed. Run: pip install httpx"}
    if not _check_available():
        return {
            "error": (
                "Set CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID "
                "environment variables"
            )
        }
    try:
        client = _get_client()
        resp = getattr(client, method)(
            _api_url(endpoint), headers=_headers(), timeout=timeout, **kwargs
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            return resp.json()
        if binary_ok:
            return {
                "success": True,
                "result_base64": base64.b64encode(resp.content).decode(),
            }
        # Non-JSON, non-binary response — try parsing, return raw on failure
        try:
            return resp.json()
        except Exception:
            return {
                "error": f"Unexpected content-type from {method.upper()} {endpoint}: {content_type}",
                "raw": resp.text[:1000],
            }
    except httpx.HTTPStatusError as exc:
        logger.error("Cloudflare API error on %s %s: %s", method.upper(), endpoint, exc)
        return {
            "error": f"Cloudflare API returned HTTP {exc.response.status_code}",
            "detail": exc.response.text[:500],
        }
    except httpx.RequestError as exc:
        logger.error("Cloudflare request failed on %s %s: %s", method.upper(), endpoint, exc)
        return {"error": f"Request to Cloudflare API failed: {exc}"}


def _post(endpoint: str, payload: dict, *, timeout: float = 120.0, binary_ok: bool = False) -> dict:
    """POST to a Cloudflare Browser Rendering endpoint and return the JSON response."""
    return _request("post", endpoint, json=payload, timeout=timeout, binary_ok=binary_ok)


def _get(
    endpoint: str, params: Optional[dict] = None, *, timeout: float = 60.0
) -> dict:
    return _request("get", endpoint, params=params, timeout=timeout)


def _delete(endpoint: str, *, timeout: float = 30.0) -> dict:
    return _request("delete", endpoint, timeout=timeout)


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


def _limit_binary_response(result: dict, max_chars: int = 50000) -> str:
    """Handle size limiting for binary (base64-encoded) responses.

    Binary payloads must not be truncated mid-string because slicing through
    base64 data produces an undecodable result *and* the truncation notice
    breaks JSON parsing.  Instead, if the serialised response would exceed the
    limit, return an error dict with metadata so the caller knows what happened.
    """
    serialized = json.dumps(result, indent=2)
    if len(serialized) <= max_chars:
        return serialized

    b64_value = result.get("result_base64", "")
    if b64_value:
        approx_bytes = len(b64_value) * 3 // 4
        return json.dumps({
            "success": result.get("success", True),
            "error": (
                f"Response too large to return ({len(serialized):,} chars, "
                f"~{approx_bytes:,} bytes decoded). "
                f"Use a smaller viewport, lower quality, or restrict to a selector."
            ),
            "size_info": {
                "total_chars": len(serialized),
                "base64_chars": len(b64_value),
                "approx_decoded_bytes": approx_bytes,
            },
        }, indent=2)

    # Non-binary but still too large — fall back to safe truncation
    return _limit_response_size(serialized, max_chars)


def handle_cf_crawl(args: dict, **kw) -> str:
    """Start an async crawl job or check status / cancel an existing one."""
    action = args.get("action", "start")

    if action == "start":
        url = args.get("url")
        if not url:
            return json.dumps({"error": "'url' is required for action=start"})
        url_err = _validate_url(url)
        if url_err:
            return json.dumps({"error": url_err})
        payload: Dict[str, Any] = {"url": url}
        if args.get("limit") is not None:
            payload["limit"] = args["limit"]
        if args.get("depth") is not None:
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
        job_id = args.get("job_id")
        if not job_id:
            return json.dumps({"error": "'job_id' is required for action=status"})
        params: Dict[str, Any] = {}
        if args.get("limit") is not None:
            params["limit"] = args["limit"]
        if args.get("cursor"):
            params["cursor"] = args["cursor"]
        if args.get("status_filter"):
            params["status"] = args["status_filter"]
        result = _get(f"crawl/{job_id}", params=params)
        return _limit_response_size(json.dumps(result, indent=2))

    elif action == "cancel":
        job_id = args.get("job_id")
        if not job_id:
            return json.dumps({"error": "'job_id' is required for action=cancel"})
        result = _delete(f"crawl/{job_id}")
        return _limit_response_size(json.dumps(result, indent=2))

    return json.dumps({"error": f"Unknown action: {action}"})


def handle_cf_scrape(args: dict, **kw) -> str:
    """Scrape specific HTML elements from a page using CSS selectors."""
    url = args.get("url")
    if not url:
        return json.dumps({"error": "'url' is required"})
    url_err = _validate_url(url)
    if url_err:
        return json.dumps({"error": url_err})
    selectors = args.get("selectors", [])
    if isinstance(selectors, str):
        selectors = [s.strip() for s in selectors.split(",") if s.strip()]
    if not selectors:
        return json.dumps({"error": "'selectors' must be a non-empty list of CSS selectors"})
    elements = [{"selector": s} for s in selectors]
    payload: Dict[str, Any] = {"url": url, "elements": elements}
    payload.update(_build_common_opts(args))
    result = _post("scrape", payload)
    return _limit_response_size(json.dumps(result, indent=2))


def handle_cf_markdown(args: dict, **kw) -> str:
    """Convert a web page to clean Markdown."""
    if not args.get("url") and not args.get("html"):
        return json.dumps({"error": "Provide either 'url' or 'html' parameter"})
    payload: Dict[str, Any] = {}
    if args.get("url"):
        url_err = _validate_url(args["url"])
        if url_err:
            return json.dumps({"error": url_err})
        payload["url"] = args["url"]
    if args.get("html"):
        payload["html"] = args["html"]
    payload.update(_build_common_opts(args))
    result = _post("markdown", payload)
    return _limit_response_size(json.dumps(result, indent=2))


def handle_cf_json_extract(args: dict, **kw) -> str:
    """Extract structured JSON data from a page using AI."""
    if not args.get("url") and not args.get("html"):
        return json.dumps({"error": "Provide either 'url' or 'html' parameter"})
    payload: Dict[str, Any] = {}
    if args.get("url"):
        url_err = _validate_url(args["url"])
        if url_err:
            return json.dumps({"error": url_err})
        payload["url"] = args["url"]
    if args.get("html"):
        payload["html"] = args["html"]
    if args.get("prompt"):
        payload["prompt"] = args["prompt"]
    if args.get("response_format"):
        payload["response_format"] = args["response_format"]
    payload.update(_build_common_opts(args))
    result = _post("json", payload)
    return _limit_response_size(json.dumps(result, indent=2))


def handle_cf_links(args: dict, **kw) -> str:
    """Extract all links from a web page."""
    url = args.get("url")
    if not url:
        return json.dumps({"error": "'url' is required"})
    url_err = _validate_url(url)
    if url_err:
        return json.dumps({"error": url_err})
    payload: Dict[str, Any] = {"url": url}
    if args.get("visible_only"):
        payload["visibleLinksOnly"] = args["visible_only"]
    if args.get("exclude_external"):
        payload["excludeExternalLinks"] = args["exclude_external"]
    payload.update(_build_common_opts(args))
    result = _post("links", payload)
    return _limit_response_size(json.dumps(result, indent=2))


def handle_cf_content(args: dict, **kw) -> str:
    """Get fully rendered HTML content of a page (after JS execution)."""
    if not args.get("url") and not args.get("html"):
        return json.dumps({"error": "Provide either 'url' or 'html' parameter"})
    payload: Dict[str, Any] = {}
    if args.get("url"):
        url_err = _validate_url(args["url"])
        if url_err:
            return json.dumps({"error": url_err})
        payload["url"] = args["url"]
    if args.get("html"):
        payload["html"] = args["html"]
    payload.update(_build_common_opts(args))
    result = _post("content", payload)
    return _limit_response_size(json.dumps(result, indent=2))


def handle_cf_screenshot(args: dict, **kw) -> str:
    """Take a screenshot of a web page. Returns base64-encoded image."""
    url = args.get("url")
    if not url:
        return json.dumps({"error": "'url' is required"})
    url_err = _validate_url(url)
    if url_err:
        return json.dumps({"error": url_err})
    payload: Dict[str, Any] = {"url": url}
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
    result = _post("screenshot", payload, binary_ok=True)
    return _limit_binary_response(result)


def handle_cf_pdf(args: dict, **kw) -> str:
    """Render a web page as PDF. Returns base64-encoded PDF."""
    url = args.get("url")
    if not url:
        return json.dumps({"error": "'url' is required"})
    url_err = _validate_url(url)
    if url_err:
        return json.dumps({"error": url_err})
    payload: Dict[str, Any] = {"url": url}
    if args.get("pdf_options"):
        payload["pdfOptions"] = args["pdf_options"]
    if args.get("viewport"):
        payload["viewport"] = args["viewport"]
    if args.get("header_template"):
        payload["headerTemplate"] = args["header_template"]
    if args.get("footer_template"):
        payload["footerTemplate"] = args["footer_template"]
    payload.update(_build_common_opts(args))
    result = _post("pdf", payload, binary_ok=True)
    return _limit_binary_response(result)


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
