"""A tool made up for the tests: it cites 2 documents the index holds, each written another way than
the entry's name: an RFC with no space in its number, and a TI note with its revision letter in lower
case. It declares the RFC only.

Read with the repository's index (rules/references/index.json).
"""

CITES = {"ietf-rfc6585": "section 4"}

# A rate limit from RFC6585, section 4.
# An efficiency from TI's SLVA477c, equation 1.
GAIN = 2.0
