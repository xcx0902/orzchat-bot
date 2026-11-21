.PHONY: install test lint run

install:
	python -m pip install -e ".[dev]"

test:
	PYTHONPATH=src python -m pytest -q

lint:
	python -m compileall -q src tests

run:
	PYTHONPATH=src python -m orzchat_bot
