# EE Workcenter — canonical commands. ee-agent-kit/AGENTS.md names these.
VENV_PY := /opt/workcenters/ee/venv/bin/python
PY := $(shell test -x $(VENV_PY) && echo $(VENV_PY) || echo python3)

.PHONY: install doctor lint format test verify image mutate-ratings

install:            ## install or update every engine (root)
	./install.sh

doctor:             ## report engine status; the "build" of this repo is a working toolchain
	python3 tools/workcenter doctor

lint:               ## shellcheck + ruff, read-only
	shellcheck install.sh verify/verify.sh environment/setup.sh site/build.sh ee-agent-kit/lead/gate-and-push.sh
	$(PY) -m ruff check tools tests verify ee-agent-kit/lead
	$(PY) -m ruff format --check tools tests verify ee-agent-kit/lead

format:             ## apply ruff formatting
	$(PY) -m ruff format tools tests verify

test:               ## gate tests on the fixture boards
	$(PY) -m pytest -q tests

verify:             ## the full health gate: lint -> kit checks -> doctor -> tests in shards
	verify/verify.sh

mutate-ratings:     ## every change of tests/ratings_mutations.py must fail the ratings tests (minutes; not in verify)
	PYTHON=$(PY) python3 tools/workcenter mutate . --mutations tests/ratings_mutations.py --jobs 4

image:              ## build the Docker image (needs a Docker daemon)
	docker build -t ee-workcenter:dev .
