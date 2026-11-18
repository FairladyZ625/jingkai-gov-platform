PYTHON ?= python3
JKQ_PYTHONPATH := core/server:core/sdk$(if $(PYTHONPATH),:$(PYTHONPATH))

.PHONY: mock-gov dev test seed
mock-gov:
	$(MAKE) -C deploy/mock-gov serve

dev:
	PYTHONPATH="$(JKQ_PYTHONPATH)" $(PYTHON) -m uvicorn jkq.app:create_app --factory --host 127.0.0.1 --port 8000

test:
	$(PYTHON) -m pytest -q --ignore=tests/demo

seed:
	PYTHONPATH="$(JKQ_PYTHONPATH)" $(PYTHON) -m jkq.seed
