"""
Контекст проектов для промптов Claude Code.

Собирает из реестра PROJECTS (config/settings.py) структурированную справку:
- активный репозиторий и его среду запуска (venv, команда тестов);
- соседние (related) репозитории — для кросс-репо задач;
- инструкции, как Claude может работать с несколькими репо сразу
  (запускать тесты в каждом, делать commit/push и т.д.).

Используется worker'ом: build_repo_context() добавляется в конец промпта.
"""

import logging
import re
from pathlib import Path

from config.settings import ProjectConfig, settings

logger = logging.getLogger(__name__)


def detect_projects_in_text(text: str) -> list[str]:
    """Находит имена проектов из реестра, упомянутые в тексте (по границе слова)."""
    found = []
    for name in settings.PROJECTS:
        if re.search(rf"\b{re.escape(name)}\b", text, flags=re.IGNORECASE):
            found.append(name)
    return found


def _fmt_venv(cfg: ProjectConfig) -> str:
    """Человекочитаемое описание среды запуска проекта."""
    parts = []
    if cfg.venv:
        parts.append(f"venv: `{cfg.venv}` (интерпретатор: `{cfg.python_bin}`)")
    if cfg.venv_activate:
        parts.append(f"активация: `{cfg.venv_activate}`")
    return "; ".join(parts) if parts else "не задана"


def _fmt_test_cmd(cfg: ProjectConfig) -> str:
    return f"`{cfg.test_cmd}`" if cfg.test_cmd else "не задана"


def _fmt_project_block(name: str, cfg: ProjectConfig, is_active: bool) -> str:
    """Блок описания одного репозитория для промпта."""
    marker = " (АКТИВНОЕ)" if is_active else ""
    desc = f" — {cfg.description}" if cfg.description else ""
    related = ", ".join(f"`{r}`" for r in cfg.related) if cfg.related else "нет"
    return (
        f"### `{name}`{marker}{desc}\n"
        f"- путь: `{cfg.path}`\n"
        f"- среда: {_fmt_venv(cfg)}\n"
        f"- тесты: {_fmt_test_cmd(cfg)}\n"
        f"- связанные репо: {related}"
    )


def _collect_related_projects(project: str) -> list[tuple[str, ProjectConfig]]:
    """Прямые соседи активного проекта (без дубликатов)."""
    active = settings.PROJECTS.get(project)
    if not active:
        return []
    result = []
    for name in active.related:
        cfg = settings.PROJECTS.get(name)
        if cfg:
            result.append((name, cfg))
    return result


def build_repo_context(
    project: str,
    extra_projects: list[str] | None = None,
    prompt_text: str = "",
) -> str:
    """
    Строит текстовый блок контекста о репозиториях для промпта Claude.

    Args:
        project: имя активного проекта (рабочая директория задачи).
        extra_projects: доп. проекты, которые нужно включить в контекст.
        prompt_text: исходный промпт — из него авто-детектятся упомянутые
            проекты (например, «задача касается askai»).

    Returns:
        Markdown-блок для добавления в конец промпта. Пустая строка,
        если проект неизвестен.
    """
    active = settings.PROJECTS.get(project)
    if not active:
        logger.warning(f"Проект '{project}' не найден в реестре, контекст не добавлен")
        return ""

    # Авто-детект проектов, упомянутых в промпте (включая доп. контекст)
    extra_projects = list(extra_projects or [])
    for name in detect_projects_in_text(prompt_text):
        if name not in extra_projects and name != project:
            extra_projects.append(name)

    blocks = [_fmt_project_block(project, active, is_active=True)]

    # Соседи + явно переданные доп. проекты, без дубликатов и без активного
    related_names = list(active.related)
    for extra in extra_projects or []:
        if extra not in related_names:
            related_names.append(extra)

    for name in related_names:
        cfg = settings.PROJECTS.get(name)
        if cfg and name != project:
            blocks.append(_fmt_project_block(name, cfg, is_active=False))

    multi_repo_hint = ""
    if len(blocks) > 1:
        multi_repo_hint = (
            "\n\n## Как работать с несколькими репозиториями\n"
            "Ты можешь решать комплексные задачи, затрагивающие несколько репо:\n"
            "1. Меняй файлы в любом из перечисленных репо по необходимости "
            "(пути указаны выше).\n"
            "2. Для запуска кода/тестов используй среду указанного репо: "
            "вызывай `{venv}/bin/python` или `{venv}/bin/<инструмент>` напрямую "
            "вместо активации (`source activate`).\n"
            "3. Прогоняй тесты в КАЖДОМ затронутом репо своей командой тестов.\n"
            "4. Коммить и пушь изменения в каждом репо отдельно, "
            "с атомарными сообщениями.\n"
            "5. Если правка в одном репо меняет контракт (API, proto, схему), "
            "проверь и обнови потребителей в связанных репо."
        )

    return (
        "\n\n## Контекст репозиториев продукта\n"
        + "\n\n".join(blocks)
        + multi_repo_hint
    )
