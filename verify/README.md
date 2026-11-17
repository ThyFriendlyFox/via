# verify/

`make verify` runs `verify.sh`: lint, kit checks, doctor, then the tests.
The tests step runs `testshards.py`: 1 pytest process per processor, side
by side, and 1 verdict from all of them.

## Files

| File | What it is |
|---|---|
| `verify.sh` | The health gate. Its last lines give each step's seconds. |
| `testshards.py` | Splits `tests/` into shards, runs them, joins the results. Standard library only. Loaded into pytest with `-p testshards`, it logs each collected id and each test report. |
| `shards.csv` | Each test file's seconds, whether it starts an engine, and why it must run alone. |

## shards.csv

| Column | Meaning |
|---|---|
| `file` | The test file, from the repository's root. `*` is the row for a file the table does not list. |
| `seconds` | The file's time inside a shard of the gate: setup, call and teardown of each test, summed from the shard's `log.jsonl`. |
| `engine` | `yes` when a test of the file starts an engine (kicad-cli, ngspice, FreeRouting, openEMS, a chip tool); `no` otherwise. A shard runs its `no` files first, so that their failures show early. |
| `alone` | Empty, or why the file cannot run beside another. Such a file runs in the shard `serial`, after the others. |

The seconds are the mean of 2 whole runs of the gate in 4 shards on
2026-11-17, on a machine of 4 processors: 1840 tests, 1989.3 s and
1991.7 s of test time. A file takes longer in a shard than alone, as 4
shards share the processors: the same tests took 1554.4 s in 1 process
(`1821 passed, 1 skipped, 18 deselected, 1 warning in 1557.70s`), and
`tests/test_chips.py` took 251.9 s there and 326.2 s in a shard. `*` takes
44.2 s, the mean of the 45 files ((1989.3 + 1991.7) / 2 / 45). The
`engine` column comes from a run with a shim in front of each engine on
`PATH` that logged the test that started it, and from reading the files
that run an engine the shim does not see (openEMS, KiCad's `pcbnew`
module, the chip tools in their own folder).

## How the split works

1. The files are sorted by their seconds, the longest first.
2. Each goes to the shard with the least seconds so far.
3. A file with a reason in `alone` goes to the shard `serial` instead.
4. In each shard the `no` files run first, then the `yes` files.

## When the gate is red

`testshards.py` prints 1 line per cause after `TESTS RED:`.

| Line | What to do |
|---|---|
| `FAILED <id> (shard N)` | A test failed. Run its file alone: `python -m pytest <file> -q`. |
| `shard N exited <code>` | pytest in that shard did not pass. Its log is under the `logs:` folder the run printed. |
| `shard N ended with no summary line` | The shard was killed or crashed. Read the end of its `pytest.log`. |
| `missing: <id>` | 1 process collects the test, and no shard ran it. |
| `not collected: <id>` | A shard ran a test that 1 process does not collect. |
| `run 2 times: <id>` | 2 shards ran the same test. |
| `logs kept: <folder>` | Each shard's `pytest.log`, `log.jsonl` and tmp_path folders are there. A green run deletes its folder. |
| `not in the table: <file>` | Not red: the file got the `*` seconds. Add its row with the seconds of a run. |

## Keeping the table true

1. Run the tests step and keep its logs:
   `python verify/testshards.py run --work /tmp/shards-1`.
2. Sum the `seconds` of each file's records in `/tmp/shards-1/shard-*/log.jsonl`
   (1 JSON object a line; the file is the part of `id` before `::`) and write
   them into `seconds`.
3. A new test file that runs an engine gets `yes`.
4. A file gets a reason in `alone` only when a run side by side showed it
   fail and the cause cannot be fixed in the test.
