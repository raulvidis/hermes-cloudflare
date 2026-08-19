"""Unit tests for the hermes-cloudflare plugin.

Covers pure logic only (no network, no credentials): URL/SSRF validation,
header sanitization, binary extraction, file output, response cache,
backoff, R2 parameter validation, and tool-schema consistency.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import pathlib
import time

import pytest

PLUGIN_PATH = (
    pathlib.Path(__file__).parent.parent / "hermes-cloudflare-plugin" / "__init__.py"
)


@pytest.fixture(scope="module")
def cf():
    spec = importlib.util.spec_from_file_location("hermes_cloudflare_plugin", PLUGIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# URL validation / SSRF guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "https://10.0.0.1/",
        "https://192.168.1.1/",
        "https://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://0.0.0.0/",
    ],
)
def test_validate_url_blocks_private_ips(cf, url):
    err = cf._validate_url(url)
    assert err is not None
    assert "private/internal" in err


@pytest.mark.parametrize(
    "url",
    [
        # Alternate IP encodings that resolve to loopback
        "http://2130706433/",          # integer form of 127.0.0.1
        "http://0x7f000001/",          # hex form of 127.0.0.1
        "http://0177.0.0.1/",          # octal form of 127.0.0.1
    ],
)
def test_validate_url_blocks_encoded_loopback(cf, url):
    err = cf._validate_url(url)
    assert err is not None


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://localhost./",                    # trailing-dot bypass attempt
        "http://metadata.google.internal/",
        "http://METADATA.GOOGLE.INTERNAL./",     # case + trailing dot
    ],
)
def test_validate_url_blocks_hostnames(cf, url):
    err = cf._validate_url(url)
    assert err is not None
    assert "blocked hostname" in err


def test_validate_url_rejects_scheme(cf):
    assert cf._validate_url("ftp://example.com/") is not None
    assert cf._validate_url("file:///etc/passwd") is not None


def test_validate_url_allows_public_ip_literal(cf):
    # IP literals skip DNS resolution, so this works without network access.
    assert cf._validate_url("https://8.8.8.8/") is None


# ---------------------------------------------------------------------------
# Header sanitization
# ---------------------------------------------------------------------------


def test_sanitize_headers_ok(cf):
    assert cf._sanitize_extra_headers({"X-Foo": "bar"}) == {"X-Foo": "bar"}


def test_sanitize_headers_strips_sensitive(cf):
    out = cf._sanitize_extra_headers({"Authorization": "x", "X-Ok": "y", "Cookie": "c"})
    assert out == {"X-Ok": "y"}


@pytest.mark.parametrize("bad", ["a\rb", "a\nb", "a\x00b"])
def test_sanitize_headers_rejects_control_chars(cf, bad):
    with pytest.raises(ValueError):
        cf._sanitize_extra_headers({"X-Bad": bad})
    with pytest.raises(ValueError):
        cf._sanitize_extra_headers({bad: "value"})


def test_sanitize_headers_rejects_bad_types(cf):
    with pytest.raises(ValueError):
        cf._sanitize_extra_headers(["not", "a", "dict"])
    with pytest.raises(ValueError):
        cf._sanitize_extra_headers({1: "x"})
    with pytest.raises(ValueError):
        cf._sanitize_extra_headers({"X-Foo": 42})


# ---------------------------------------------------------------------------
# Binary extraction / file output
# ---------------------------------------------------------------------------


def test_extract_base64_variants(cf):
    assert cf._extract_base64({"result_base64": "AAA"}) == "AAA"
    assert cf._extract_base64({"result": "BBB"}) == "BBB"
    assert cf._extract_base64({"result": {"screenshot": "CCC"}}) == "CCC"
    assert cf._extract_base64({"result": {"pdf": "DDD"}}) == "DDD"
    assert cf._extract_base64({"result": {"content": "<html>"}}) is None
    assert cf._extract_base64({}) is None


def test_publish_binary_saves_file(cf, tmp_path):
    data = b"fake image bytes"
    b64 = base64.b64encode(data).decode()
    target = tmp_path / "sub" / "shot.png"
    info = cf._publish_binary(
        {"success": True, "result_base64": b64},
        {"output_path": str(target)},
        "image/png",
    )
    assert info is not None and "error" not in info
    assert info["saved_to"] == str(target)
    assert info["bytes"] == len(data)
    assert target.read_bytes() == data


def test_publish_binary_no_request_returns_none(cf):
    assert cf._publish_binary({"success": True, "result_base64": "AAA"}, {}, "image/png") is None


def test_publish_binary_propagates_api_error(cf, tmp_path):
    info = cf._publish_binary(
        {"error": "boom"}, {"output_path": str(tmp_path / "x.png")}, "image/png"
    )
    assert info == {"error": "boom"}


def test_publish_binary_no_binary_content(cf, tmp_path):
    info = cf._publish_binary(
        {"success": True, "result": {"content": "<html>"}},
        {"output_path": str(tmp_path / "x.png")},
        "image/png",
    )
    assert info is not None and "No binary content" in info["error"]


def test_publish_binary_requires_r2_key(cf):
    info = cf._publish_binary(
        {"success": True, "result_base64": "AAA"}, {"r2_bucket": "mybucket"}, "image/png"
    )
    assert info is not None and "r2_key" in info["error"]


def test_write_output_file_rejects_directory(cf, tmp_path):
    err = cf._write_output_file(str(tmp_path), b"data")
    assert err is not None and "directory" in err


# ---------------------------------------------------------------------------
# R2 validation (fails before any network call)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bucket", ["", "A", "UPPER", "-bad", "bad-", "a" * 100, "has space"])
def test_upload_to_r2_rejects_bad_bucket(cf, bucket):
    out = cf._upload_to_r2(bucket, "key.png", b"x", "image/png")
    assert "Invalid R2 bucket" in out["error"]


@pytest.mark.parametrize("key", ["", "/leading-slash", "a/../b"])
def test_upload_to_r2_rejects_bad_key(cf, key):
    out = cf._upload_to_r2("valid-bucket-name", key, b"x", "image/png")
    assert "Invalid R2 object key" in out["error"]


# ---------------------------------------------------------------------------
# Response cache
# ---------------------------------------------------------------------------


def test_cache_roundtrip_and_expiry(cf, monkeypatch):
    cf._RESPONSE_CACHE.clear()
    key = cf._cache_key("post", "https://x/y", {"json": {"url": "https://example.com"}})
    assert cf._cache_get(key) is None
    cf._cache_put(key, {"success": True, "result": 1})
    assert cf._cache_get(key) == {"success": True, "result": 1}
    # Deterministic key
    assert key == cf._cache_key("post", "https://x/y", {"json": {"url": "https://example.com"}})
    # Expire by rewinding monotonic
    real_monotonic = time.monotonic
    monkeypatch.setattr(cf.time, "monotonic", lambda: real_monotonic() + cf._RESPONSE_CACHE_TTL + 1)
    assert cf._cache_get(key) is None
    cf._RESPONSE_CACHE.clear()


def test_cache_evicts_oldest(cf, monkeypatch):
    cf._RESPONSE_CACHE.clear()
    monkeypatch.setattr(cf, "_RESPONSE_CACHE_MAX_ENTRIES", 2)
    for i in range(3):
        cf._cache_put(f"k{i}", {"success": True, "i": i})
    assert "k0" not in cf._RESPONSE_CACHE
    assert "k1" in cf._RESPONSE_CACHE and "k2" in cf._RESPONSE_CACHE
    cf._RESPONSE_CACHE.clear()


# ---------------------------------------------------------------------------
# Backoff
# ---------------------------------------------------------------------------


def test_backoff_honours_retry_after(cf):
    assert cf._backoff_delay(1, "5") == 5.0
    assert cf._backoff_delay(1, "9999") == 30.0          # capped
    assert cf._backoff_delay(1, "not-a-number") > 0       # falls back


def test_backoff_grows_with_attempts(cf):
    d1 = max(cf._backoff_delay(1) for _ in range(50))
    d3 = max(cf._backoff_delay(3) for _ in range(50))
    assert d3 > d1
    assert cf._backoff_delay(10) <= 8.0                   # capped at base 8s


# ---------------------------------------------------------------------------
# Handler argument validation (no network involved)
# ---------------------------------------------------------------------------


def test_ai_chat_requires_input(cf):
    assert "error" in json.loads(cf.handle_cf_ai_chat({}))


def test_ai_chat_rejects_bad_model(cf):
    out = json.loads(cf.handle_cf_ai_chat({"prompt": "hi", "model": "bad model!!"}))
    assert "Invalid model name" in out["error"]


def test_ai_chat_rejects_bad_messages(cf):
    out = json.loads(cf.handle_cf_ai_chat({"messages": "nope"}))
    assert "messages" in out["error"]


def test_dns_rejects_bad_hostname(cf):
    out = json.loads(cf.handle_cf_dns({"name": "bad host name!"}))
    assert "Invalid hostname" in out["error"]


def test_dns_rejects_bad_type(cf):
    out = json.loads(cf.handle_cf_dns({"name": "example.com", "type": "BOGUS"}))
    assert "Unsupported record type" in out["error"]


def test_dns_requires_name(cf):
    assert "error" in json.loads(cf.handle_cf_dns({}))


def test_pdf_requires_url_or_html(cf):
    out = json.loads(cf.handle_cf_pdf({}))
    assert "url" in out["error"] and "html" in out["error"]


def test_snapshot_rejects_bad_formats(cf):
    out = json.loads(cf.handle_cf_snapshot({"url": "https://example.com", "formats": ["bogus"]}))
    assert "Invalid formats" in out["error"]


# ---------------------------------------------------------------------------
# Tool registry / schema consistency
# ---------------------------------------------------------------------------


def test_tools_registry_consistent(cf):
    names = [t["name"] for t in cf.TOOLS]
    assert len(names) == len(set(names)), "duplicate tool names"
    assert len(names) == 12
    for tool in cf.TOOLS:
        assert callable(tool["handler"])
        assert tool["schema"]["name"] == tool["name"]
        assert tool["description"]
        assert tool["emoji"]


def test_plugin_yaml_matches_tools(cf):
    yaml_path = PLUGIN_PATH.parent / "plugin.yaml"
    text = yaml_path.read_text()
    tools_section = text.split("provides_tools:")[1]
    declared = {
        line.strip().lstrip("- ").strip()
        for line in tools_section.splitlines()
        if line.strip().startswith("- ")
    }
    registered = {t["name"] for t in cf.TOOLS}
    assert declared == registered
