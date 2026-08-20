#!/usr/bin/env python3
"""Тестовый скрипт для проверки работы очереди"""

import asyncio
from src.worker.worker import main

if __name__ == "__main__":
    asyncio.run(main())
    