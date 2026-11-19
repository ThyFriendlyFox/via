# Via — canonical commands. ee-agent-kit/AGENTS.md names these.
VENV_PY := /opt/workcenters/ee/venv/bin/python
PY := $(shell test -x $(VENV_PY) && echo $(VENV_PY) || echo python3)

SCOPE_BASE ?= origin/main

.PHONY: install doctor lint format test kit check verify image mutate-ratings scope verify-site

# The kit's own tests that `make check` runs before the files a change names in TESTS.
KIT_TESTS := tests/test_gate_rule.py tests/test_lead_skills.py tests/test_docs.py::test_no_commit_names_an_assistant_as_its_author

install:            ## install or update every engine (root)
	./install.sh

doctor:             ## report engine status; the "build" of this repo is a working toolchain
	python3 tools/workcenter doctor

lint:               ## shellcheck + ruff, read-only
	shellcheck install.sh verify/verify.sh environment/setup.sh site/build.sh ee-agent-kit/lead/gate-and-push.sh tools/ci/apt_archive.sh tools/ci/apt_cache.sh
	$(PY) -m ruff check tools tests verify ee-agent-kit/lead
	$(PY) -m ruff format --check tools tests verify ee-agent-kit/lead

format:             ## apply ruff formatting
	$(PY) -m ruff format tools tests verify

test:               ## gate tests on the fixture boards
	$(PY) -m pytest -q tests

kit:                ## the gate's kit checks alone (2 copies of every kit skill, frontmatter, CLAUDE.md = AGENTS.md, MISTAKES and PROCESSES); no lock
	verify/verify.sh kit

check: lint kit     ## the fast checks before a push to a work branch: lint, kit checks, the kit's tests, TESTS="<files>"; no engine
	WORKCENTER_NO_ENGINES=1 $(PY) -m pytest -q -p no:cacheprovider -m "not engine" $(KIT_TESTS) $(TESTS)

scope:              ## fast or full: what the change from SCOPE_BASE to the working tree needs
	$(PY) tools/ci/scope.py --base "$$(git merge-base $(SCOPE_BASE) HEAD)"

verify-site:        ## the fast gate for every change, KiCad's libraries hidden; starts no engine
	verify/verify.sh site

verify:             ## the full health gate: lint -> kit checks -> doctor -> tests in shards
	verify/verify.sh

mutate-ratings:     ## every change of tests/ratings_mutations.py must fail the ratings tests (minutes; not in verify)
	PYTHON=$(PY) python3 tools/workcenter mutate . --mutations tests/ratings_mutations.py --jobs 4

image:              ## build the Docker image (needs a Docker daemon)
	docker build -t via:dev .
