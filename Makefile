# Makefile del proyecto. Centraliza los comandos que usamos a diario.
# Uso: `make <target>` (ej: `make lint`). `make` o `make help` lista los targets.

# Lintamos main.py + todos los src/*.py. El wildcard toma cualquier archivo nuevo
# automáticamente, así no hay que mantener una lista de archivos a mano.
LINT_FILES := main.py $(wildcard src/*.py)

.DEFAULT_GOAL := help
.PHONY: help install format lint check check-setup run

help:  ## Muestra esta ayuda
	@echo Targets disponibles:
	@echo   make install      - Instala dependencias del stack local
	@echo   make format       - Formatea el codigo (isort + black)
	@echo   make lint         - Corre las 5 herramientas (igual que VSCode)
	@echo   make check        - Alias de lint (no modifica archivos)
	@echo   make check-setup  - Diagnostico del entorno (Ollama, VTS, .env)
	@echo   make run          - Arranca el bot

install:  ## Instala dependencias del stack local
	poetry install

format:  ## Formatea el código con isort + black
	poetry run isort $(LINT_FILES)
	poetry run black $(LINT_FILES)

lint:  ## Corre las 5 herramientas que usa VSCode (no modifica archivos)
	poetry run flake8 $(LINT_FILES)
	poetry run isort --check-only $(LINT_FILES)
	poetry run black --check $(LINT_FILES)
	poetry run mypy $(LINT_FILES)
	poetry run pylint $(LINT_FILES)
	poetry run pyright $(LINT_FILES)

check: lint  ## Alias de lint (verificación sin modificar)

check-setup:  ## Diagnóstico del entorno (Ollama, VTS, variables .env)
	poetry run python -m src.check_setup

run:  ## Arranca el bot
	poetry run python main.py
