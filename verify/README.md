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

The seconds come from 1 whole run of `verify.sh` in 4 shards on
2026-11-18, on a machine of 4 processors: 2873 tests, 2852 s of test time
(`testshards.py table` on that run's logs). A file takes longer in a shard
than alone, as 4 shards share the processors: on 2026-11-17, 1840 tests
took 1554.4 s in 1 process
(`1821 passed, 1 skipped, 18 deselected, 1 warning in 1557.70s`), and
`tests/test_chips.py` took 251.9 s there and 326.2 s in a shard. `*` takes
41.9 s, the mean of the 68 files. The `engine` column comes from a run
with a shim in front of each engine on `PATH` that logged the test that
started it, and from reading the files that run an engine the shim does
not see (openEMS, KiCad's `pcbnew` module, the chip tools in their own
folder). The 15 files new to the table on 2026-11-18 were marked by
reading them: `yes` where a test runs kicad-cli or ngspice, or the engine
lock's own commands.

The 16 files new to the table on 2026-11-18 (77ad649) were measured
alone, 1 run each, under the engine lock at a load under 2. Their
`engine` comes from their `engine` marks
(`pytest --collect-only -m engine`). Seconds alone are lower than
seconds in a shard: the next whole run's `testshards.py table` replaces
them.

## How the split works

1. The files are sorted by their seconds, the longest first.
2. Each goes to the shard with the least seconds so far.
3. A file with a reason in `alone` goes to the shard `serial` instead.
4. In each shard the `no` files run first, then the `yes` files.

## When the gate is red

`testshards.py` prints 1 line per cause after `TESTS RED:`.

| Line | What to do |
|---|---|
| `FAILED <id> (shard N) at T s` | A test failed, T seconds after its shard started; the line comes while the other shards run on. Run its file alone: `python -m pytest <file> -q`. |
| `why: <id>, failed at call (shard N):` | What pytest reported for it, under `  \| `: the first 10 and last 30 lines of the traceback (the test's frame, the line that raised, the exception), each captured output's last 10 lines, 300 characters a line. `an error at setup` or `an error at teardown` for a fixture's error. The first 10 such reports are printed. A character UTF-8 cannot write is printed escaped. |
| `why: <file> could not be collected (shard N):` | The file's import or collection error, from the shard, or `(the collection in 1 process)` when only 1 process met it. |
| `why: shard N ended with no report from pytest (...)` | The shard was killed, crashed or cut off. The line names the test it started last and did not end, then the last 30 lines of its `pytest.log`; after a crash, its `Fatal Python error` and the stack, the test's frame first. |
| `why: shard N exited <code> and no test failed` | pytest reached its end of session and stopped for another reason (5: no tests; 3: an internal error, with its `INTERNALERROR>` lines). The end of its `pytest.log` follows. A usage error or a conftest that cannot load (4) never reaches the end of session: it shows as `why: shard N ended with no report from pytest (exit 4)`, with pytest's error in the lines below. |
| `why: shard N was running <id> when stopped` | The gate was stopped by a signal (a CI time limit): the test each shard had started and not ended (`was between tests` when it had none). |
| `why: N more failed tests' reports are not printed here` | More than 10 failures: the rest are counted; each shard's whole report is its `pytest.log` under the folder named. |
| `shard N exited <code>` | pytest in that shard did not pass. Its log is under the `logs:` folder the run printed. |
| `shard N ended before pytest's end of session` | The shard was killed, crashed, or a test ended the process (even with exit 0). The end of its `pytest.log` is printed under `why: shard N ended ...`. |
| `the collection in 1 process exited <code>` | `pytest --collect-only` failed in 1 process. Its last 5 lines follow. |
| `missing: <id>` | 1 process collects the test, and no shard ran it. |
| `not collected: <id>` | A shard ran a test that 1 process does not collect. |
| `run 2 times: <id>` | 2 shards ran the same test. |
| `marks differ: <id>: ...` | The test's skip or xfail marks say one thing in its shard and another in 1 process: the shard's environment changed the verdict. |
| `not judged: <id>: skipped inside the test` | Not red: the test called `pytest.skip` in its shard. Whether 1 process skips it too is not known without running it there. |
| `stopped by signal N` | The run got SIGTERM or SIGHUP. It killed every shard's process group before it exited 128 + N. |
| `--work <folder> holds the logs of an earlier run` | Exit 2. The logs are appended to: name an empty folder, or remove that one. |
| `logs kept: <folder>` | Each shard's `pytest.log`, `log.jsonl` and tmp_path folders are there. A green run deletes its folder. |
| `not in the table: <file>` | Not red: the file got the `*` seconds. Add its row with the seconds of a run. |

## Keeping the table true

1. Run the tests step 1 or more times and keep the logs:
   `python verify/testshards.py run --work /tmp/shards-1`, then the same
   with `/tmp/shards-2`. Each folder must be empty or new. A red run
   keeps its own folder, and its seconds count: a failed test still took
   its time.
2. Print the table with the mean seconds of the runs:
   `python verify/testshards.py table /tmp/shards-1 /tmp/shards-2`.
   Write what it prints into `shards.csv` with the Write tool. It keeps each
   file's `engine` and `alone`; a file new to the table gets the `*` row's
   `engine`.
3. A new test file that runs no engine gets `no`.
4. A file gets a reason in `alone` only when a run side by side showed it
   fail and the cause cannot be fixed in the test. 1 file has one:
   `tests/test_fab.py` lists the files of a fixture before and after a DRC
   run, and kicad-cli writes `~rc_divider.kicad_pro.lck` into that fixture
   while another shard runs a gate on it.
