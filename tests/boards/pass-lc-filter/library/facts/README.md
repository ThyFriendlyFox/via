# The facts of pass-lc-filter's parts

This fixture's library holds no part's facts. Its decks' L1 and C1 are a filter made up for the
frequency plan's tests, and no schematic or parts file names them.

Without this folder the SIM gate would read `tests/boards/library/facts`, the facts of the other
fixtures' parts, which hold a capacitor's DC bias curve. The fixture has no schematic, so the gate
would print its deck parts as not judged (tools/partdata.py).
