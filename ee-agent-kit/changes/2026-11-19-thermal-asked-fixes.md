### Fixed
- SIM: a row of `sim/thermal.json` whose `mpn` is not the board part's number fails and holds nothing: the gate judged the part on another part's facts.
- SIM: a row under a reference the board does not fit (another reference, or a part marked not fitted) is named, a warning (a failure with `--strict`), and is not judged: it failed the gate before at 106.26 C for a part the board does not have.
- SIM: a run that SPRA953D's equation 5 judged names `theta_jc` as its figure in the record, with `equation` `5`; what theta_ja or the stated case gave stands under `beside`.
- The fixtures `pass-sim-bus` and `pass-legend-dense` give their made-up U1 a number in `parts.csv`, so the SIM gate does not take it for a part with a thermal figure.
