import json
import re
from collections.abc import Mapping
from typing import Any

_SENSITIVE_KEY = re.compile(
    r"(?i)(api[-_ ]?key|authorization|cookie|password|passwd|secret|token|credential)"
)
_SENSITIVE_VALUE = re.compile(r"(?i)(bearer\s+[a-z0-9._-]+|sk-[a-z0-9_-]{8,}|tvly-[a-z0-9_-]{8,})")
_MARKDOWN_URL = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", re.I)
_PLAIN_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_TRAILING_URL_PUNCTUATION = ".,;:!?，。；：！？）)]}》】"


def redact(value: Any, *, max_chars: int = 800) -> str:
    """Create a bounded, frontend-safe tool summary."""

    def clean(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                str(key): "[已脱敏]" if _SENSITIVE_KEY.search(str(key)) else clean(child)
                for key, child in item.items()
            }
        if isinstance(item, (list, tuple)):
            return [clean(child) for child in item[:20]]
        if isinstance(item, str):
            return _SENSITIVE_VALUE.sub("[已脱敏]", item)
        if item is None or isinstance(item, (bool, int, float)):
            return item
        return str(item)

    if isinstance(value, str):
        rendered = clean(value)
    else:
        rendered = json.dumps(clean(value), ensure_ascii=False, default=str)
    rendered = str(rendered)
    return rendered if len(rendered) <= max_chars else f"{rendered[: max_chars - 1]}…"


def safe_error(_: Exception | None = None, fallback: str = "操作失败，请稍后重试。") -> str:
    """Never leak provider payloads, paths, or credentials to clients."""
    return fallback


def remove_unverified_urls(text: str, allowed_urls: set[str]) -> tuple[str, list[str]]:
    """Remove model-generated URLs that were not returned by a trusted tool.

    The model response is streamed before it can be checked, so callers can
    emit a final replacement event when this function changes the text.
    """

    allowed = {url.strip() for url in allowed_urls if url.strip()}
    removed: list[str] = []

    def replace_markdown(match: re.Match[str]) -> str:
        label, url = match.groups()
        if url in allowed:
            return match.group(0)
        removed.append(url)
        return label

    checked = _MARKDOWN_URL.sub(replace_markdown, text)

    def replace_plain(match: re.Match[str]) -> str:
        raw = match.group(0)
        candidate = raw.rstrip(_TRAILING_URL_PUNCTUATION)
        suffix = raw[len(candidate) :]
        if candidate in allowed:
            return raw
        removed.append(candidate)
        return "[未验证链接已移除]" + suffix

    return _PLAIN_URL.sub(replace_plain, checked), list(dict.fromkeys(removed))


def contains_sensitive_memory(text: str) -> bool:
    patterns = (
        r"(?i)password|passwd|密码",
        r"(?i)api[-_ ]?key|secret|token|密钥|令牌",
        r"(?i)credit\s*card|银行卡|信用卡|cvv|支付密码",
        r"\b\d{15,19}\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)
