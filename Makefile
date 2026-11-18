# EE Workcenter — canonical commands. ee-agent-kit/AGENTS.md names these.
VENV_PY := /opt/workcenters/ee/venv/bin/python
PY := $(shell test -x $(VENV_PY) && echo $(VENV_PY) || echo python3)

SCOPE_BASE ?= origin/main

.PHONY: install doctor lint format test verify image mutate-ratings scope verify-site

install:            ## install or update every engine (root)
	./install.sh

doctor:             ## report engine status; the "build" of this repo is a working toolchain
	python3 tools/workcenter doctor

lint:               ## shellcheck + ruff, read-only
	shellcheck install.sh verify/verify.sh environment/setup.sh site/build.sh ee-agent-kit/lead/gate-and-push.sh
	$(PY) -m ruff check tools tests ee-agent-kit/lead
	$(PY) -m ruff format --check tools tests ee-agent-kit/lead

format:             ## apply ruff formatting
	$(PY) -m ruff format tools tests

test:               ## gate tests on the fixture boards
	$(PY) -m pytest -q tests

scope:              ## fast or full: what the change from SCOPE_BASE to the working tree needs
	$(PY) tools/ci/scope.py --base "$$(git merge-base $(SCOPE_BASE) HEAD)"

verify-site:        ## the fast gate for a change `make scope` calls fast; starts no engine
	verify/verify.sh site

verify:             ## the full health gate: lint -> doctor -> test -> kit checks
	verify/verify.sh

mutate-ratings:     ## every change of tests/ratings_mutations.py must fail the ratings tests (minutes; not in verify)
	PYTHON=$(PY) python3 tools/workcenter mutate . --mutations tests/ratings_mutations.py --jobs 4

image:              ## build the Docker image (needs a Docker daemon)
	docker build -t ee-workcenter:dev .
