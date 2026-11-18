"""The mutation list of install.sh's apt step (PROCESSES.md P18 step 4, kept for a script as for firmware).

`workcenter mutate . --mutations tests/install_mutations.py --jobs 4` runs each change below in its
own copy of the paths COPY names, and each must fail TEST. The command reads the 3 names as literals
and runs nothing of this file. `tests/test_install_apt.py` checks that each old text is in install.sh
exactly 1 time, so an edit of the step that moves an anchor fixes the anchor in the same commit.

The tests point the install root into their own folder, so a change that drops the source guard
stops inside that folder (IA12).
"""

TEST = "${PYTHON:-python3} -m pytest tests/test_install_apt.py -x -q -p no:cacheprovider"
COPY = ["install.sh", "pyproject.toml", "tests", "tools"]

# fmt: off
MUTATIONS = [
    ("IA01 kicad_index: apt's exit code alone", "install.sh",
     'if ((rc == 0)) && [[ -z "$APT_SAID" ]]; then', "if ((rc == 0)); then"),
    ("IA02 kicad_index: 1 try fewer", "install.sh",
     "try <= KICAD_INDEX_TRIES; try++", "try < KICAD_INDEX_TRIES; try++"),
    ("IA03 kicad_index: a wait after the last try", "install.sh",
     "if ((try < KICAD_INDEX_TRIES)); then", "if true; then"),
    ("IA04 candidates: any archive", "install.sh",
     'elif [[ "$cand" != 10.* || "$from" != "$src"* ]]; then', 'elif [[ "$cand" != 10.* ]]; then'),
    ("IA05 candidates: any version", "install.sh",
     'elif [[ "$cand" != 10.* || "$from" != "$src"* ]]; then', 'elif [[ "$from" != "$src"* ]]; then'),
    ("IA06 candidates: no package missing", "install.sh",
     'if [[ -z "$cand" || "$cand" == "(none)" ]]; then', 'if false; then'),
    ("IA07 candidates: the check not called", "install.sh",
     "    kicad_candidates_check\n", "    true\n"),
    ("IA08 apt_shown: the filter's code", "install.sh",
     'return "${codes[0]}"', 'return "${codes[1]}"'),
    ("IA09 apt_shown: always 0", "install.sh",
     'return "${codes[0]}"', "return 0"),
    ("IA10 download: a stall read as a failure", "install.sh",
     "if ((rc == 124)); then\n    stop", "if ((rc == 999)); then\n    stop"),
    ("IA11 install: may download again", "install.sh",
     "    -o APT::Get::Download=false ", "    "),
    ("IA12 the guard", "install.sh",
     'if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then', "if true; then"),
    ("IA13 progress: grep buffers", "install.sh",
     '"$@" 2> "$errors" | grep --line-buffered -E', '"$@" 2> "$errors" | grep -E'),
    ("IA14 progress: sed buffers", "install.sh",
     "sed -u 's/^/[apt] /'\n  codes=", "sed 's/^/[apt] /'\n  codes="),
    ("IA15 the backstop", "install.sh",
     "  if ! kicad10_present; then\n    seen=", "  if false; then\n    seen="),
    ("IA16 kicad_index: another source's line", "install.sh",
     'grep -F "$KICAD_PPA_URL" <<< "$out"', 'grep -F "Failed" <<< "$out"'),
    ("IA17 download: no bound", "install.sh",
     'apt_shown timeout "$APT_DOWNLOAD_TIMEOUT" apt-get', "apt_shown apt-get"),
    ("IA18 the link's path a literal again", "install.sh",
     'ln -sfn "${SRC_DIR}/tools/workcenter" "$WORKCENTER_LINK"',
     'ln -sfn "${SRC_DIR}/tools/workcenter" /usr/local/bin/workcenter'),
]
# fmt: on
