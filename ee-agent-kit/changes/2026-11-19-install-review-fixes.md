### Fixed
- Between 2 cut tries of the index update, CI moves to the end of its mirror list the silent host apt asks first; it moved the one apt asks last.
- A bare Ubuntu's index update, in the image build, gets 3 tries 20 s apart, as the main one, where it had 1.
- A cut try in which every package source printed a line says that a host which began a file and then slowed is not named; a package source that is switched off (`Enabled: no`) is not named.
- CI's `fast` job has 20 minutes, not 15: a run of 2026-11-19 took 711 s.
