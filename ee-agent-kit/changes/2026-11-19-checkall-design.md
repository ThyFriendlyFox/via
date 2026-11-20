### Changed
- `workcenter design --check` compares every file the design writes but the board, the copied rule file and `Design.files` too, flags a rule file the design would not write, and names the 1 step (`--rules-only` for a header that alone differs); `--json` reads a design file that prints while it builds.
