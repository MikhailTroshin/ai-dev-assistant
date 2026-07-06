#!/usr/bin/env python3
"""Тест async запуска Claude Code"""

import asyncio
import sys
from pathlib import Path

async def test_async():
    print("Тест async запуска Claude Code")
    
    prompt = "Скажи 'Привет из async!'"
    working_dir = Path("/home/ws/mtroshin/ragllm")
    
    print(f"Промпт: {prompt}")
    print(f"Рабочая директория: {working_dir}")
    
    try:
        process = await asyncio.create_subprocess_exec(
            "claude",
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir
        )
        
        print(f"Process PID: {process.pid}")
        print("Ожидание результата...")
        
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=30
        )
        
        print(f"\nReturn code: {process.returncode}")
        print(f"Output:\n{stdout.decode('utf-8')}")
        
        if stderr:
            print(f"Stderr:\n{stderr.decode('utf-8')}")
        
        return process.returncode == 0
        
    except asyncio.TimeoutError:
        print("❌ Таймаут")
        return False
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_async())
    sys.exit(0 if success else 1)