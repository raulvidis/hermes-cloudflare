# hermes-cloudflare

Cloudflare Browser Rendering plugin for [hermes-agent](https://github.com/NousResearch/hermes-agent) — crawl, scrape, and extract content from web pages using Cloudflare's headless browser API.

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

## Requirements

- hermes-agent v0.3.0+
- Python 3.10+
- `httpx` (installed automatically by install.sh)
- Cloudflare account with Browser Rendering enabled (available on Free and Paid plans)

## License

MIT
