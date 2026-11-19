"""`workcenter fields`: a run whose ports did not settle runs again, deeper.

openEMS checked its end criterion every 4 s of the clock, so where it stopped hung on the machine's
load. `OpenEMS.run` now ends a run itself once the ports have settled (`fields.ended`); a run whose
column reads none settled all the same runs again with the box's energy let fall further.
No engine runs here: the engine is a stand-in that settles from a given margin on.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import fields  # noqa: E402


class StopsEarly:
    """openEMS as the Wyvern lane's port 3 ran it on 2026-11-17: on a busy machine its check of the end
    criterion, every 4 s of the clock, fell at step 13410 and the ports had not settled; at 13708 and
    later they had. Here a run settles from the run ended once the box's energy falls `settles_at` dB
    under the end criterion."""

    program = "openEMS"

    def __init__(self, settles_at: float):
        self.settles_at, self.margins = settles_at, []

    def run(self, run, timeout, model, margin_db):
        self.margins.append(margin_db)
        return True, "Time for 13410 iterations"

    def column(self, run, model, driven):
        if self.margins[-1] < self.settles_at:
            raise fields.NotSettled("the port signals did not settle 40 dB under their peak")
        return [[0.5]]


def test_a_run_that_stopped_before_the_ports_settled_runs_again_deeper(tmp_path):
    """The first run ends at the criterion (ENGINE_MARGIN_DB, 0 dB further) and has not settled: it runs
    again to 20 dB under it, settles, and gives its column, with no fault. Margins: 0, then 20."""
    engine = StopsEarly(settles_at=20.0)
    model = {"settings": {"timeout_s": 60}}
    column, error = fields.run_port(engine, model, tmp_path, 1)
    assert (column, error) == ([[0.5]], None)
    assert engine.margins == [fields.ENGINE_MARGIN_DB, 20.0]


def test_a_run_that_never_settles_is_a_fault_after_the_deepest_run(tmp_path):
    """Margins ENGINE_MARGIN_DB, 20 and 30 dB: none settles, and the fault names the deepest, 30 dB."""
    engine = StopsEarly(settles_at=99.0)
    model = {"settings": {"timeout_s": 60}}
    column, error = fields.run_port(engine, model, tmp_path, 3)
    assert column is None and engine.margins == [fields.ENGINE_MARGIN_DB, 20.0, 30.0]
    assert error == (
        "openEMS on port 3 ended without a result: the port signals did not settle 40 dB under their peak"
        " (run 3 times, the last to 30 dB under the end criterion)"
    )
