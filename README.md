# hermes-cloudflare

Cloudflare Browser Rendering plugin for [hermes-agent](https://github.com/NousResearch/hermes-agent) — crawl, scrape, and extract content from web pages using Cloudflare's headless browser API.

> ℹ️ Cloudflare has renamed Browser Rendering to **Browser Run** — same API, endpoints unchanged.

## Tools

| Tool | Description |
|------|-------------|
| `cf_crawl` | Async website crawling with depth/limit controls, format selection (HTML/Markdown/JSON), include/exclude patterns, sitemap discovery |
| `cf_scrape` | CSS-selector-based element extraction (text, HTML, attributes, dimensions) |
| `cf_markdown` | Convert pages to clean Markdown (handles JS-heavy sites) |
| `cf_json_extract` | AI-powered structured data extraction (Workers AI / Llama 3.3 70B) with prompt + JSON schema |
| `cf_links` | Link discovery with visible-only and external domain filtering |
| `cf_content` | Fully rendered HTML after JavaScript execution |
| `cf_screenshot` | Page screenshots (full-page, element, viewport control, PNG/JPEG/WebP) |
| `cf_pdf` | Page-to-PDF with headers/footers, margins, scale |
| `cf_snapshot` | Multiple formats (HTML, screenshot, Markdown, a11y tree) in a single request |
| `cf_accessibility_tree` | Accessibility tree of a page (roles, names, values) after JS execution |
| `cf_ai_chat` | Workers AI text generation via REST (Llama models; needs "Workers AI - Read" token permission) |
| `cf_dns` | DNS-over-HTTPS record lookups (A, AAAA, MX, TXT, …) — no credentials needed |

### Saving binary output

Screenshots and PDFs can exceed the inline response limit. Instead of returning
base64, save them directly:

- `output_path` — write the decoded file locally (supported by `cf_screenshot`, `cf_pdf`, `cf_snapshot`)
- `r2_bucket` + `r2_key` — upload to an R2 bucket (requires "Workers R2 Storage - Edit" token permission)

`cf_pdf` also accepts raw `html` instead of a `url` for generating PDFs from custom HTML/CSS.

### Reliability

Read endpoints are cached for 5 minutes (renders are billed per browser-second),
and requests are automatically retried with backoff on rate limits (429) and
transient server errors (5xx).

## Installation

### Quick install (hermes-agent v0.3.0+)

```bash
curl -sSL https://raw.githubusercontent.com/raulvidis/hermes-cloudflare/main/install.sh | bash
```

### Manual install

```bash
git clone https://github.com/raulvidis/hermes-cloudflare.git
mkdir -p ~/.hermes/plugins
cp -r hermes-cloudflare/hermes-cloudflare-plugin ~/.hermes/plugins/hermes-cloudflare
pip install httpx
```

## Configuration

Set these environment variables (in your shell profile or `.env`):

```bash
export CLOUDFLARE_API_TOKEN="your-api-token"
export CLOUDFLARE_ACCOUNT_ID="your-account-id"
```

### Getting your credentials

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com/profile/api-tokens)
2. Create a token with **Browser Rendering - Edit** permission
   (add **Workers AI - Read** for `cf_ai_chat` and **Workers R2 Storage - Edit** for R2 uploads)
3. Copy your Account ID from the dashboard sidebar

## Usage examples

Once installed, hermes-agent can use the tools directly:

**Crawl a website:**
> Crawl https://docs.example.com and return the content as Markdown

**Scrape specific elements:**
> Scrape all h1 tags and .price elements from https://shop.example.com

**Extract structured data with AI:**
> Extract all product names, prices, and ratings from https://store.example.com as JSON

**Get page as Markdown:**
> Convert https://blog.example.com/post to Markdown

**Take a screenshot:**
> Take a full-page screenshot of https://example.com

**Capture multiple formats at once:**
> Get the Markdown, screenshot, and accessibility tree of https://example.com in one request

**Inspect page structure:**
> Show me the accessibility tree of https://app.example.com so I can see the interactive elements

**Save a PDF of a page:**
> Render https://example.com/report as a PDF and save it to /tmp/report.pdf

**Resolve a DNS record:**
> What are the MX records for example.com?

## Requirements

- hermes-agent v0.3.0+
- Python 3.10+
- `httpx` (installed automatically by install.sh)
- Cloudflare account with Browser Rendering enabled (available on Free and Paid plans)

## License

MIT
