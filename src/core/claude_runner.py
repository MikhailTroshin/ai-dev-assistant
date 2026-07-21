import asyncio
import logging
from pathlib import Path
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)


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
        Запускает Claude Code с промптом
        """
        timeout = timeout or settings.CLAUDE_TIMEOUT
        
        try:
            logger.info(f"Запуск Claude Code с промптом: {prompt[:100]}...")
            
            cmd = [self.claude_path, prompt]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir
            )
            
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


claude_runner = ClaudeRunner()
