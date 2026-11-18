# What apt prints, for the tests of install.sh's apt step

`tests/test_install_apt.py` runs the apt step of `install.sh` against stand-ins of `apt-get`,
`apt-cache` and the other programs it calls. The stand-ins answer with these lines.

- `policy-ppa.txt`: `apt-cache policy kicad kicad-symbols kicad-footprints kicad-templates` on the
  workcenter's cloud machine on 2026-11-18, apt 2.8.3, KiCad 10.0.8 installed from the PPA. Copied as
  printed.
- `policy-ubuntu-kicad.txt`: the same command's shape when `kicad`'s only candidate is Ubuntu's own
  7.0.11+dfsg-1build4. Made by hand from `policy-ppa.txt`: `Installed: (none)`, and for `kicad` only
  the Ubuntu version left. The version and the archive are the ones apt fetched in CI job 134932219722
  at 15:57:24 (`Get:118 http://azure.archive.ubuntu.com/ubuntu noble/universe amd64 kicad amd64
  7.0.11+dfsg-1build4 [36.1 MB]`).

The `W:` and `E:` lines in the tests are copied from the logs of CI jobs 134932219722 (15:57:17) and
134906707485 (15:44:22).
