#!/bin/bash

# Активируем виртуальное окружение
source venv/bin/activate

# Запускаем worker
arq src.worker.worker.WorkerSettings