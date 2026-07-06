import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ClaudeRunner:
    """Обёртка для запуска Claude Code через CLI"""
    
    def __init__(self, claude_path: str = "claude"):
        self.claude_path = claude_path
    
    async def run(
        self,
        prompt: str,
        working_dir: Optional[Path] = None,
        timeout: int = 300
    ) -> dict:
        """
        Запускает Claude Code с промптом
        
        Args:
            prompt: Промпт для Claude Code
            working_dir: Рабочая директория (по умолчанию текущая)
            timeout: Таймаут в секундах
            
        Returns:
            dict с результатами:
            {
                "success": bool,
                "output": str,
                "error": str | None
            }
        """
        try:
            logger.info(f"Запуск Claude Code с промптом: {prompt[:100]}...")
            
            # Формируем команду
            cmd = [self.claude_path, prompt]
            
            # Запускаем процесс
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir
            )
            
            # Ждём завершения с таймаутом
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                
                output = stdout.decode('utf-8').strip()
                error = stderr.decode('utf-8').strip()
                
                success = process.returncode == 0
                
                result = {
                    "success": success,
                    "output": output,
                    "error": error if not success else None,
                    "returncode": process.returncode
                }
                
                logger.info(f"Claude Code завершён: success={success}")
                return result
                
            except asyncio.TimeoutError:
                process.kill()
                logger.error(f"Claude Code превысил таймаут {timeout}с")
                return {
                    "success": False,
                    "output": "",
                    "error": f"Timeout after {timeout} seconds",
                    "returncode": -1
                }
                
        except Exception as e:
            logger.error(f"Ошибка запуска Claude Code: {e}")
            return {
                "success": False,
                "output": "",
                "error": str(e),
                "returncode": -1
            }


# Singleton
claude_runner = ClaudeRunner()
