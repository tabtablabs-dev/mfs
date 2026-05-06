PYTHON ?= python3

.PHONY: install deploy smoke verify bench compile

install:
	$(PYTHON) -m venv .venv
	. .venv/bin/activate && pip install -r requirements.txt

deploy:
	modal deploy modal_rustfs_app.py

smoke:
	$(PYTHON) smoke_test.py

verify:
	$(PYTHON) smoke_test.py --verify-existing

bench:
	$(PYTHON) smoke_test.py --bench

compile:
	$(PYTHON) -m py_compile modal_rustfs_app.py smoke_test.py
