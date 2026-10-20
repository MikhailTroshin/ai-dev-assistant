"""
Лёгкий клиент для получения названия Jira-задачи (summary).

Не использует MCP/skills: worker'у нужно только поле summary для подписи
кнопок меню «Продолжить работу». Креды берёт из ~/.claude/.jira-credentials
(тот же файл, что и jira_query.py), результат кэшируется в Redis на 24 часа.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import requests

from config.settings import settings

logger = logging.getLogger(__name__)

# Кэш Redis: jira_summary:<KEY> -> название задачи
_CACHE_TTL = 24 * 3600
# Таймаут одного HTTP-запроса к Jira (сек)
_HTTP_TIMEOUT = 10

_CREDS_FILE = Path.home() / ".claude" / ".jira-credentials"


def _load_credentials() -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Читает креды Jira из файла (url, email, api_token)."""
    try:
        with open(_CREDS_FILE, "r", encoding="utf-8") as f:
            creds = json.load(f)
        return creds.get("url"), creds.get("email"), creds.get("api_token")
    except Exception as e:
        logger.warning(f"Не удалось прочитать {_CREDS_FILE}: {e}")
        return None, None, None


async def _get_cache(redis_client, key: str) -> Optional[str]:
    try:
        raw = await redis_client.get(f"jira_summary:{key}")
        return raw.decode("utf-8") if raw else None
    except Exception:
        return None


async def _set_cache(redis_client, key: str, summary: str) -> None:
    try:
        await redis_client.set(f"jira_summary:{key}", summary, ex=_CACHE_TTL)
    except Exception as e:
        logger.warning(f"Не удалось закэшировать summary {key}: {e}")


def _fetch_summary_sync(jira_key: str, url: str, email: str, api_token: str) -> Optional[str]:
    """Синхронный запрос summary (выполняется в executor)."""
    try:
        resp = requests.get(
            f"{url}/rest/api/3/issue/{jira_key}",
            auth=(email, api_token),
            headers={"Accept": "application/json"},
            params={"fields": "summary"},
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code == 200:
            summary = resp.json().get("fields", {}).get("summary", "").strip()
            return summary or None
        logger.warning(f"Jira вернула {resp.status_code} для {jira_key}")
    except Exception as e:
        logger.warning(f"Ошибка запроса summary {jira_key}: {e}")
    return None


async def fetch_jira_summary(jira_key: str, redis_client=None) -> Optional[str]:
    """
    Возвращает название задачи по ключу, или None (недоступно — не критично).

    redis_client: опциональный клиент redis.asyncio для кэша.
    """
    if not jira_key:
        return None

    if redis_client is not None:
        cached = await _get_cache(redis_client, jira_key)
        if cached:
            return cached

    url, email, api_token = _load_credentials()
    if not all([url, email, api_token]):
        return None

    loop = asyncio.get_running_loop()
    summary = await loop.run_in_executor(
        None, _fetch_summary_sync, jira_key, url, email, api_token
    )

    if summary and redis_client is not None:
        await _set_cache(redis_client, jira_key, summary)

    return summary
