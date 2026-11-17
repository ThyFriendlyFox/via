"""A tool made up for the tests: it declares 4 documents of the index and cites another revision or
edition of each.

Read with the repository's index (rules/references/index.json).
"""

CITES = {
    "ecss-q-st-30-11c-rev2": "table 6-1",
    "pozar-microwave-engineering-4": "equation 3.195",
    "freedesktop-basedir-0.8": "section 2",
    "bipm-si-brochure-9": "table 1",
}

# A derating from ECSS-Q-ST-30-11C Rev.1, table 6-1.
# A line impedance from Pozar, 2nd edition, equation 3.195.
# A cache folder from the XDG Base Directory Specification 0.6, section 2.
# A unit from the SI Brochure, 8th edition, table 1.
GAIN = 2.0
