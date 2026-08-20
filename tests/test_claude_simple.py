#!/usr/bin/env python3
"""Простой тест запуска Claude Code через subprocess"""

import subprocess
import sys

def test_claude():
    print("Тест 1: Проверка доступности claude")
    result = subprocess.run(
        ["which", "claude"],
        capture_output=True,
        text=True
    )
    print(f"which claude: {result.stdout.strip()}")
    if result.returncode != 0:
        print("❌ Claude не найден в PATH")
        return False
    
    print("\nТест 2: Проверка версии")
    result = subprocess.run(
        ["claude", "--version"],
        capture_output=True,
        text=True,
        timeout=10
    )
    print(f"Версия: {result.stdout.strip()}")
    
    print("\nТест 3: Простой промпт")
    result = subprocess.run(
        ["claude", "Скажи 'Привет, я работаю!'"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd="/home/ws/mtroshin/ragllm"
    )
    print(f"Return code: {result.returncode}")
    print(f"Output:\n{result.stdout}")
    if result.stderr:
        print(f"Stderr:\n{result.stderr}")
    
    return result.returncode == 0

if __name__ == "__main__":
    try:
        success = test_claude()
        sys.exit(0 if success else 1)
    except subprocess.TimeoutExpired:
        print("❌ Таймаут при выполнении")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)
        