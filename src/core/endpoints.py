"""
Реестр эндпоинтов и моделей с горячей перезагрузкой из JSON-файла.

Файл (по умолчанию `data/endpoints.json`) перечитывается при каждом обращении,
если его mtime изменился — перезапускать бота/воркер не нужно.

Формат файла:

    {
      "default_endpoint": "default",
      "default_model": "glm-5.2",
      "endpoints": {
        "default": {
          "name": "Default (LiteLLM)",
          "base_url": "http://10.105.0.22:4000",
          "auth_token": "sk-...",
          "models": [{"id": "glm-4.7", "name": "GLM-4.7"}],
          "extra_env": {"ANTHROPIC_API_KEY": "..."}
        },
        "free": {
          "name": "Free models",
          "base_url": "https://free-proxy/anthropic",
          "auth_token": "",
          "models": [{"id": "nemotron", "name": "Nemotron"}]
        }
      }
    }
"""

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class Endpoint:
    """Описание одного API-эндпоинта (провайдера/прокси)."""

    id: str
    name: str
    base_url: str = ""
    auth_token: Optional[str] = None
    models: list[dict] = field(default_factory=list)
    extra_env: dict[str, str] = field(default_factory=dict)

    @property
    def model_ids(self) -> list[str]:
        return [m["id"] for m in self.models if m.get("id")]


def _normalize_models(raw) -> list[dict]:
    """Приводит список моделей к единому виду [{id, name}]."""
    models: list[dict] = []
    if not isinstance(raw, list):
        return models
    for item in raw:
        if isinstance(item, str):
            models.append({"id": item, "name": item})
        elif isinstance(item, dict) and item.get("id"):
            models.append({"id": str(item["id"]), "name": str(item.get("name") or item["id"])})
    return models


class EndpointRegistry:
    """
    Загружает эндпоинты/модели из JSON-файла и перечитывает его при изменении.

    Кэширует разобранные данные; при изменении mtime файла перечитывает его.
    Если файл повреждён — сохраняет последний рабочий набор и пишет в лог.
    """

    def __init__(self, path: Optional[Path] = None):
        self._lock = threading.Lock()
        self._mtime: Optional[int] = None
        self._endpoints: dict[str, Endpoint] = {}
        self._default_endpoint: str = getattr(settings, "DEFAULT_ENDPOINT", "default")
        self._default_model: Optional[str] = getattr(settings, "DEFAULT_MODEL", None)
        self._path = Path(path) if path else self._resolve_path()

    # ==================== Загрузка ====================

    @staticmethod
    def _resolve_path() -> Path:
        """
        Путь к файлу реестра.

        Приоритет: env ENDPOINTS_FILE → settings.ENDPOINTS_FILE.
        Относительный путь ищется от текущего каталога (в контейнере бота это
        /app, у воркера — корень проекта), затем — от PROJECT_PATH.
        """
        raw = os.getenv("ENDPOINTS_FILE") or getattr(settings, "ENDPOINTS_FILE", "data/endpoints.json")
        path = Path(raw).expanduser()
        if path.is_absolute():
            return path

        candidates = [Path.cwd() / path]
        project_path = getattr(settings, "PROJECT_PATH", None)
        if project_path:
            candidates.append(Path(project_path) / path)
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    @property
    def path(self) -> Path:
        return self._path

    def reload(self) -> None:
        """Принудительное перечитывание файла."""
        with self._lock:
            self._mtime = None
            self._load(force=True)

    def _ensure_fresh(self) -> None:
        """Перечитывает файл, если он изменился с прошлой загрузки."""
        with self._lock:
            try:
                mtime = self._path.stat().st_mtime_ns
            except FileNotFoundError:
                if self._mtime is not None or self._endpoints:
                    # Файл пропал — оставляем последний рабочий набор
                    return
                self._seed_file()
                try:
                    mtime = self._path.stat().st_mtime_ns
                except OSError:
                    mtime = None
            except OSError as e:
                logger.warning(f"Не удалось проверить {self._path}: {e}")
                return

            if mtime != self._mtime:
                # Фиксируем mtime сразу: если файл битый, не логируем ошибку
                # на каждое обращение — только один раз на версию файла.
                self._mtime = mtime
                self._load(force=True)

    def _load(self, force: bool = False) -> None:
        """Читает и парсит файл реестра (вызывается под lock)."""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning(f"Файл реестра эндпоинтов не найден: {self._path}")
            return
        except OSError as e:
            logger.error(f"Не удалось прочитать {self._path}: {e}")
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Некорректный JSON в {self._path}: {e}. Используется предыдущая версия.")
            return

        if not isinstance(data, dict):
            logger.error(f"Ожидался объект в {self._path}. Используется предыдущая версия.")
            return

        endpoints: dict[str, Endpoint] = {}
        raw_endpoints = data.get("endpoints") or {}
        if not isinstance(raw_endpoints, dict):
            logger.error(f"Секция 'endpoints' в {self._path} должна быть объектом.")
            return

        for ep_id, cfg in raw_endpoints.items():
            if not isinstance(cfg, dict):
                logger.warning(f"Эндпоинт '{ep_id}' пропущен: ожидался объект")
                continue
            endpoints[str(ep_id)] = Endpoint(
                id=str(ep_id),
                name=str(cfg.get("name") or ep_id),
                base_url=str(cfg.get("base_url") or ""),
                auth_token=cfg.get("auth_token") or None,
                models=_normalize_models(cfg.get("models")),
                extra_env={str(k): str(v) for k, v in (cfg.get("extra_env") or {}).items()},
            )

        if not endpoints:
            logger.error(f"В {self._path} нет ни одного эндпоинта. Используется предыдущая версия.")
            return

        default_endpoint = str(data.get("default_endpoint") or self._default_endpoint)
        if default_endpoint not in endpoints:
            default_endpoint = next(iter(endpoints))

        default_model = data.get("default_model") or self._default_model

        changed = (
            force
            or default_endpoint != self._default_endpoint
            or default_model != self._default_model
            or {k: v.base_url for k, v in endpoints.items()} != {k: v.base_url for k, v in self._endpoints.items()}
            or sorted(endpoints) != sorted(self._endpoints)
        )

        self._endpoints = endpoints
        self._default_endpoint = default_endpoint
        self._default_model = default_model
        try:
            self._mtime = self._path.stat().st_mtime_ns
        except OSError:
            self._mtime = None

        if changed:
            logger.info(
                f"Реестр эндпоинтов обновлён из {self._path}: "
                f"эндпоинты={list(endpoints)}, default={default_endpoint}"
            )

    def _seed_file(self) -> None:
        """Создаёт файл реестра из встроенных настроек, если его нет."""
        seed = {
            "default_endpoint": getattr(settings, "DEFAULT_ENDPOINT", "default"),
            "default_model": getattr(settings, "DEFAULT_MODEL", None),
            "endpoints": {
                name: {
                    "name": getattr(cfg, "name", name),
                    "base_url": getattr(cfg, "base_url", ""),
                    "auth_token": getattr(cfg, "auth_token", None),
                    "models": getattr(cfg, "models", []),
                    "extra_env": getattr(cfg, "extra_env", {}),
                }
                for name, cfg in (getattr(settings, "ENDPOINTS", {}) or {}).items()
            },
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._path)
            logger.info(f"Создан файл реестра эндпоинтов: {self._path}")
        except OSError as e:
            logger.error(f"Не удалось создать {self._path}: {e}")

    # ==================== Публичный API ====================

    def endpoints(self) -> dict[str, Endpoint]:
        """Все настроенные эндпоинты."""
        self._ensure_fresh()
        return dict(self._endpoints)

    def get(self, endpoint_id: str) -> Optional[Endpoint]:
        """Эндпоинт по id (None, если не найден)."""
        self._ensure_fresh()
        return self._endpoints.get(endpoint_id)

    def default_endpoint(self) -> str:
        """Id эндпоинта по умолчанию."""
        self._ensure_fresh()
        return self._default_endpoint

    def default_model(self) -> Optional[str]:
        """Модель по умолчанию."""
        self._ensure_fresh()
        return self._default_model

    def models(self, endpoint_id: str) -> list[dict]:
        """
        Модели, доступные на эндпоинте.

        Если у эндпоинта модели не перечислены — берутся общие из settings.
        """
        self._ensure_fresh()
        endpoint = self._endpoints.get(endpoint_id)
        if endpoint and endpoint.models:
            return endpoint.models
        return _normalize_models(getattr(settings, "AVAILABLE_MODELS", []))


# Синглтон
endpoints_registry = EndpointRegistry()
