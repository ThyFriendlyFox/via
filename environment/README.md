# Cloud environment for the EE Workcenter

A Claude Code cloud environment named `EE Workcenter` gives every session
opened in it the engines from this repository. The environment, not the
board repository, carries the software.

## Settings

| Setting | Value |
|---|---|
| Setup script | the 3 commands in `environment/setup.sh` |
| Network access | Custom: the Trusted defaults plus the hosts below |
| Environment variables | none required |

## Network hosts to add

Trusted access already allows PyPI, the Ubuntu archives, and GitHub.
Add these:

| Host | Used by |
|---|---|
| `ppa.launchpadcontent.net` | KiCad 10 packages |
| `keyserver.ubuntu.com` | `install.sh` fetches the PPA signing key |
| `api.launchpad.net` | the same key from Launchpad, when the keyserver does not answer |
| `release-assets.githubusercontent.com` | FreeRouting JAR download |

## Time budget

The setup script finishes in about 2 to 4 minutes on a fresh VM. Anthropic
snapshots the filesystem after the first run only if the script finishes in
roughly 5 minutes. The script skips `kicad-packages3d` (3.3 GB installed) to
stay inside that window. Later sessions start from the snapshot and pay
nothing.

## The chip engines

The setup script installs no chip engine. To design a chip in the
environment, run the install with `INSTALL_CHIP=1`:

```
INSTALL_CHIP=1 bash /opt/workcenters/ee/src/install.sh
```

The step adds 1.9 GB and took 32 s on the workcenter's machine, with the
4 Ubuntu packages already there. It reaches these hosts beyond the ones
above:

| Host | Used by |
|---|---|
| `conda.anaconda.org` | micromamba, and the OpenROAD, Magic and Netgen packages |
| `fossi-foundation.github.io` | ciel's index of process kit builds |
| `github.com`, `release-assets.githubusercontent.com` | the process kit's 2 archives, release assets of `fossi-foundation/ciel-releases` |

`ee-agent-kit/docs/ENGINES.md`, "The chip engines", lists each engine, its
version and its traps.

## How a board repository uses it

1. Open the board repository in the `EE Workcenter` environment.
2. Add this repository as a second repository when its skills should load.
   Skills from an attached repository load; hooks and `.mcp.json` do not.
3. Without the second repository, the tools are still on `PATH` as
   `workcenter`, and the manifest is at `/opt/workcenters/ee/WORKCENTER.md`.
