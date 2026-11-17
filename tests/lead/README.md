# The lead's journal, canned

`journal.jsonl` is the journal `tests/test_lead.py` gives
`ee-agent-kit/lead/landed.py`, in the form `ee-agent-kit/lead/README.md`
names. It holds 3 pieces of work:

| Branch | Holds | landed.py says |
|---|---|---|
| `alpha` | a build, a review with 2 findings, a fix (1 fixed, 1 refuted) | finished; head is the fix's |
| `beta` | a build, a review with 1 finding (as JSON text), no fix | waits for the fix |
| `gamma` | a build, no review | waits for a review |

The file also holds 1 line that is no JSON, which is passed over. The
hashes are stand-ins: 40 times 1 hex digit.
