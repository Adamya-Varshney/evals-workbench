PY ?= python

.PHONY: dev setup test e2e seed serve

dev:
	$(PY) dev.py dev

setup:
	$(PY) dev.py setup

test:
	$(PY) dev.py test

e2e:
	$(PY) dev.py e2e

seed:
	$(PY) dev.py seed

serve:
	$(PY) dev.py serve
