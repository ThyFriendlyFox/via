### Fixed
- install.sh bounds and watches every download, not only the main one: the openEMS step's libraries and a bare Ubuntu's first packages come in passes within `APT_OTHER_TIMEOUT`, and a file a host did not serve is asked again. In an image build of 2026-11-19 a 520 for 1 library left openEMS unable to start.
- A try of the index update that its bound ends names the package sources that had not answered and shows apt's last lines, and CI moves a silent mirror host to the end of its list before the next try.
- CI's download gives a failed file's host up at once where it keeps a mirror list (`APT_FILE_RETRIES`, `APT_FILE_TIMEOUT`); a person's computer keeps 3 tries and 60 s.
- CI's `fast` job has 15 minutes, not 10: a slow runner used 578 of its 600 s.
