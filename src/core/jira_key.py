import re

# Паттерн Jira-ключа: 2+ заглавные буквы, дефис, цифры (AA-123, ER-12345)
JIRA_KEY_RE = re.compile(r"\b([A-Z]{2,})-(\d+)\b")


def extract_jira_key(text: str | None) -> str | None:
    """
    Первый Jira-ключ в тексте (AA-123), или None.
    Для /task и /code-review ключ — аргумент команды, для остальных
    команд — если упомянут в тексте.
    """
    m = JIRA_KEY_RE.search(text or "")
    return m.group(0) if m else None
