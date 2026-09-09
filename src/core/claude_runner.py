import asyncio
import logging
import os
import signal
import time
from pathlib import Path
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)


class _OutputCollector:
    """Инкрементально читает stdout/stderr процесса в буферы (без дедлока)."""

    def __init__(self, process: asyncio.subprocess.Process):
        self._process = process
        self._tasks: list[asyncio.Task] = []
        self.stdout = ""
        self.stderr = ""

    async def _read_stream(self, stream, attr: str) -> None:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            setattr(self, attr, getattr(self, attr) + chunk.decode("utf-8", errors="replace"))

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._read_stream(self._process.stdout, "stdout")),
            asyncio.create_task(self._read_stream(self._process.stderr, "stderr")),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


class ClaudeRunner:
    """Обёртка для запуска Claude Code через CLI"""

    def __init__(self, claude_path: str = None):
        self.claude_path = claude_path or settings.CLAUDE_CODE_PATH

    async def run(
        self,
        prompt: str,
        working_dir: Optional[Path] = None,
        timeout: Optional[int] = None
    ) -> dict:
        """
        Запускает Claude Code с промптом.

        Возвращает:
            {
                "success": bool,
                "output": str,       # stdout (или частичный при таймауте)
                "error": str | None, # человекочитаемое описание ошибки
                "returncode": int,
                "logs": str,         # технический лог выполнения для отладки
                "timed_out": bool,
                "duration": float
            }
        """
        timeout = timeout or settings.CLAUDE_TIMEOUT
        started = time.monotonic()

        log_lines = [
            f"=== Claude Code run ===",
            f"cmd: {self.claude_path}",
            f"cwd: {working_dir}",
            f"timeout: {timeout}s",
            f"prompt ({len(prompt)} chars): {prompt[:500]}{'...' if len(prompt) > 500 else ''}",
        ]

        try:
            cmd = [self.claude_path, prompt]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                # Отдельная группа процессов: позволяет убить всё дерево
                # (включая дочерние процессы Claude Code) при таймауте
                start_new_session=True,
            )
            log_lines.append(f"pid: {process.pid}")

            collector = _OutputCollector(process)
            collector.start()

            # ВАЖНО: wait_for(process.wait()) при таймауте отменяет внутренний
            # waiter процесса, после чего повторный wait() зависает (баг asyncio).
            # Поэтому ждем через гонку wait_task vs sleep, не отменяя wait_task.
            wait_task = asyncio.create_task(process.wait())
            timeout_task = asyncio.create_task(asyncio.sleep(timeout))
            done, _ = await asyncio.wait(
                {wait_task, timeout_task}, return_when=asyncio.FIRST_COMPLETED
            )
            timeout_task.cancel()

            if wait_task in done:
                await collector.stop()

                duration = time.monotonic() - started
                output = collector.stdout.strip()
                error_out = collector.stderr.strip()
                success = process.returncode == 0

                log_lines.append(f"finished: rc={process.returncode}, duration={duration:.1f}s")
                log_lines.append(f"stdout ({len(output)} chars)")
                if error_out:
                    log_lines.append(f"stderr: {error_out[:2000]}")

                return {
                    "success": success,
                    "output": output,
                    "error": None if success else (error_out or f"Claude Code завершился с кодом {process.returncode}"),
                    "returncode": process.returncode,
                    "logs": "\n".join(log_lines),
                    "timed_out": False,
                    "duration": duration,
                }

            # --- Таймаут ---
            # Забираем частичный вывод ДО убийства процесса
            partial_out = collector.stdout
            partial_err = collector.stderr
            # Убиваем всю группу процессов (start_new_session=True => pgid == pid):
            # иначе выжившие дети держат пайпы открытыми и wait() зависает
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            # Дожидаемся фактического завершения (reap зомби), wait_task не отменяем
            try:
                await asyncio.wait_for(asyncio.shield(wait_task), timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("Процесс не завершился после killpg")
            await collector.stop()
            duration = time.monotonic() - started

            log_lines.append(f"TIMEOUT after {timeout}s, partial stdout: {len(partial_out)} chars")
            if partial_err:
                log_lines.append(f"stderr (partial): {partial_err[:2000]}")

            return {
                "success": False,
                "output": partial_out.strip(),
                "error": (
                    f"⏱ Превышен таймаут {timeout} сек.\n"
                    f"Задача не была завершена — результат может быть неполным.\n"
                    f"Частичный вывод ({len(partial_out)} символов) сохранён в деталях задачи."
                    if partial_out else
                    f"⏱ Превышен таймаут {timeout} сек. Вывод не получен."
                ),
                "returncode": -1,
                "logs": "\n".join(log_lines),
                "timed_out": True,
                "duration": duration,
            }

        except Exception as e:
            duration = time.monotonic() - started
            logger.error(f"Ошибка запуска Claude Code: {e}")
            log_lines.append(f"EXCEPTION: {type(e).__name__}: {e}")
            return {
                "success": False,
                "output": "",
                "error": f"Не удалось запустить Claude Code: {type(e).__name__}: {e}",
                "returncode": -1,
                "logs": "\n".join(log_lines),
                "timed_out": False,
                "duration": duration,
            }


claude_runner = ClaudeRunner()
