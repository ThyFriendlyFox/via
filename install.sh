#!/usr/bin/env bash
# install.sh — install the EE Workcenter toolchain on Ubuntu 24.04.
#
# Usage:
#   sudo ./install.sh            install or update every engine
#   ./install.sh --check         report engine status; install nothing
#   sudo ./install.sh --chip     install or update the chip engines only
#   sudo ./install.sh --openems  install or update the field solver (openEMS) only
#   sudo ./install.sh --freerouting2  install or update the second router (FreeRouting 2.5.0
#                                     and the Java 25 it needs) only
#
# Every step skips work that is already done, so the script is safe to
# run again. A required step that fails exits non-zero, so a cloud
# environment that runs this as its setup script fails to start instead
# of starting without tools.
#
# Environment overrides:
#   WORKCENTER_ROOT       install root            (default /opt/workcenters/ee)
#   FREEROUTING_VERSION   FreeRouting release     (default below)
#   FREEROUTING_SHA256    expected JAR checksum   (default below; empty skips the check)
#   FREEROUTING_URL       JAR download URL        (default: GitHub release asset)
#   REQUIRE_FREEROUTING   1 makes a failed JAR download fatal (default 0: warn)
#   REQUIRE_OPENEMS       1 makes a failed openEMS step fatal (default 0: warn)
#   OPENEMS_POOL          where the 4 Debian packages of openEMS are fetched (default deb.debian.org)
#   INSTALL_FREEROUTING2  1 also installs the second router, FreeRouting 2.5.0 with its own
#                         Java 25, 125 MB under WORKCENTER_ROOT (default 0: the default
#                         router is FreeRouting 1.9.0)
#   REQUIRE_FREEROUTING2  1 makes a failed second-router step fatal (default 0: warn)
#   SKIP_APT              1 skips the apt step (for images that ship KiCad 10)
#   KICAD_INDEX_TRIES     tries to fetch the index of KiCad 10's package source (default 3)
#   KICAD_INDEX_WAIT      seconds between 2 tries (default 20)
#   APT_UPDATE_TIMEOUT    seconds 1 `apt-get update` of KiCad 10's index may take (default empty:
#                         no bound; CI sets 120)
#   APT_DOWNLOAD_TIMEOUT  seconds the download of the packages may take (default empty: no bound;
#                         CI sets 570). Under sudo, pass it with env: sudo drops a variable set
#                         before it (`sudo env APT_DOWNLOAD_TIMEOUT=900 ./install.sh`). It covers every
#                         pass of the download and every wait between 2, together
#   APT_DOWNLOAD_TRIES    passes of the download, when a package source does not serve a file (default 5)
#   APT_DOWNLOAD_WAIT     seconds between 2 passes (default 20)
#   APT_WATCH_WINDOW      seconds of progress by which a pass of a bounded download is judged: one that
#                         cannot finish within APT_DOWNLOAD_TIMEOUT at that rate is ended (default 120)
#   APT_SLOW_PASS_COMMAND a command run between 2 passes after a pass that was too slow, with the hosts
#                         of that pass as its last words, split at blanks (default empty: none; CI names
#                         a mode of tools/ci/apt_archive.sh that puts the slow host last)
#   KICAD_KEYRING, KICAD_SOURCES, WORKCENTER_LINK, OS_RELEASE, JVM_DIR, CA_BUNDLE, APT_ARCHIVES
#                         the paths outside WORKCENTER_ROOT the script writes or reads (defaults
#                         below); the tests point them into a folder of their own
#   INSTALL_CHIP          1 also installs the chip engines and the sky130A
#                         process kit, 1.9 GB under WORKCENTER_ROOT/chip
#                         (default 0: a board needs none of them)

# The options are the script's own when it runs as a file; a shell that sources the script (a test, to
# call 1 function) keeps its own.
if [[ "${BASH_SOURCE[0]:-}" == "$0" ]]; then
  set -euo pipefail
fi

# From standard input (`bash -s < install.sh`, `curl ... | bash`) or a process substitution
# (`bash <(curl ...)`, a pipe under /dev/fd) the script is no file of the checkout, and SRC_DIR below is
# read from it.
if [[ ! -f "${BASH_SOURCE[0]:-}" ]]; then
  printf '[install] ERROR: %s\n' "install.sh runs as a file, not from standard input: sudo ./install.sh" >&2
  exit 1
fi

WC_NAME="ee"
WC_ROOT="${WORKCENTER_ROOT:-/opt/workcenters/${WC_NAME}}"
# The checkout's folder, through any link to the script.
SRC_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

# KiCad 10 PPA, added by writing the sources file and key directly:
# add-apt-repository needs the system python's apt_pkg, which images with a
# different default python3 do not have.
KICAD_PPA_URL="https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu/"
KICAD_PPA_FPR="FDA854F61C4D0D9572BB95E5245D5502FAD7A805"   # "PPA for KiCad: 10.0 releases"
# Every path the script writes outside WC_ROOT is a variable with its real default: a test points
# each into its own folder before it sources the script.
KICAD_KEYRING="${KICAD_KEYRING:-/etc/apt/keyrings/kicad-10.0-releases.gpg}"
KICAD_SOURCES="${KICAD_SOURCES:-/etc/apt/sources.list.d/kicad-10.0-releases.sources}"
WORKCENTER_LINK="${WORKCENTER_LINK:-/usr/local/bin/workcenter}"
KICAD_PACKAGES=(kicad kicad-symbols kicad-footprints kicad-templates)
BASE_PACKAGES=(ngspice openjdk-21-jre-headless xvfb shellcheck librsvg2-bin ffmpeg
               python3 python3-venv python3-pip curl ca-certificates)
# Paths the apt step reads; a test points them into its own folder.
OS_RELEASE="${OS_RELEASE:-/etc/os-release}"
JVM_DIR="${JVM_DIR:-/usr/lib/jvm}"
# The certificates the first step looks for; a test points it into its own folder.
CA_BUNDLE="${CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}"

# The bounds of the apt step.
# The index: every computer tries it KICAD_INDEX_TRIES times, KICAD_INDEX_WAIT s apart. Launchpad's
# host flaps: on 2026-11-18 it answered 503 for the index (CI job 134932219722) and for a package file
# (job 134906707485), and within 1 minute 200 for the index and 503 for a file. A short wait rides that
# out. A long outage ends after the last try, with apt's own line.
# A person's computer gets no total bound on `apt-get update` or on the download. A slow line that
# makes progress finishes. apt ends a stall itself: a server silent for APT_FILE_TIMEOUT s is given up,
# and tried APT_FILE_RETRIES times more. The progress lines show that the run is alive.
# CI sets both bounds, in the install step of .github/workflows/ci.yml: APT_UPDATE_TIMEOUT=120 and
# APT_DOWNLOAD_TIMEOUT=570. Its `full` job has 1800 s (timeout-minutes: 30), and a stall must end with
# apt's line, not at the job's limit with none. The newest passing run (job 134941364976) used 9 s
# before this script, 27 s to unpack and set up, 28 s for the steps after apt and 670 s for
# `make verify`: 1066 s are left for the key, the updates, the waits and the download. The key fetch
# takes at most 88 s (KICAD_KEY_TIMEOUT below); 88 + 3 x 120 + 2 x 20 + 570 = 1058 s. The slowest
# update seen took 48 s (job 134906707485); the slowest download 218 s for 281.1 MB (job 134889089620).
# Either bound is a whole number of seconds; empty, the default, means no bound.
KICAD_INDEX_TRIES="${KICAD_INDEX_TRIES:-3}"
KICAD_INDEX_WAIT="${KICAD_INDEX_WAIT:-20}"
APT_UPDATE_TIMEOUT="${APT_UPDATE_TIMEOUT:-}"
APT_DOWNLOAD_TIMEOUT="${APT_DOWNLOAD_TIMEOUT:-}"
# The download: up to APT_DOWNLOAD_TRIES passes, APT_DOWNLOAD_WAIT s apart, and a pass is made again only
# when a source did not serve a file. In its log, the amd64 image build of pull request 92 on 2026-11-18
# fetched 377 files from Ubuntu and 2 from KiCad 10's source, then got 503 for `kicad` 3 times in 18 s
# (Ign, Ign, Err: apt's own tries, 95.47 s to 113.4 s) and stopped after 1 pass. apt keeps each file it
# has fetched, so a later pass asks only for the rest. APT_DOWNLOAD_TIMEOUT, when set, bounds all passes and waits together, so CI's worst case above
# stays as it is. CI and the image build set neither: they run on these defaults.
APT_DOWNLOAD_TRIES="${APT_DOWNLOAD_TRIES:-5}"
APT_DOWNLOAD_WAIT="${APT_DOWNLOAD_WAIT:-20}"
# apt's own bounds on 1 file, as before: 3 more tries, and a server silent for 60 s is given up. 4 x 60
# = 240 s on 1 silent file stays within CI's download bound, so apt names that file before the cut.
APT_FILE_RETRIES="3"
APT_FILE_TIMEOUT="60"
# The watch of a pass, when APT_DOWNLOAD_TIMEOUT is set. In CI run 44506767788 (2026-11-19, job
# 135500622487) the probe of tools/ci/apt_archive.sh measured us-east-2.ec2.archive.ubuntu.com at
# 2468910 bytes/s; 17 s later the download's 1 pass asked it for every file, 26.6 MB of them arrived in
# 550.7 s (48.3 kB/s), and the bound of 570 s ended that pass: no other host was given a turn. So each
# bounded pass is watched. Every APT_WATCH_WINDOW/24 s the watch counts the bytes in apt's archives
# folder and its partial/, where a file grows while it comes (apt 2.8.3, apt-pkg/acquire-item.cc,
# pkgAcqArchive::pkgAcqArchive). Once a window has gone by, it ends the pass when the rate of the last
# APT_WATCH_WINDOW s, kept up, would not fetch the rest of what apt said it needs ("Need to get",
# apt-private/private-install.cc) within what is left of the bound. The next pass asks again: apt keeps
# each finished file and continues a partial one (the same place). The window is 2 x APT_FILE_TIMEOUT:
# a stall that apt ends itself fills at most half of it. A pass that has all apt named, or that names
# no size, is not judged; with no bound, nothing watches. tests/test_install_apt.py holds the numbers
# (test_the_watch_ends_the_slow_pass_of_run_44506767788_in_time_for_a_second_host).
APT_WATCH_WINDOW="${APT_WATCH_WINDOW:-120}"
APT_SLOW_PASS_COMMAND="${APT_SLOW_PASS_COMMAND:-}"
# apt's archives folder (Dir::Cache::Archives); the watch only reads it. A test points it into its folder.
APT_ARCHIVES="${APT_ARCHIVES:-/var/cache/apt/archives}"
# The key fetch, on every computer that has no key yet (every fresh CI runner): each of its 2 addresses
# gets tries of at most KICAD_KEY_TIMEOUT s (curl --max-time), and a try is made again only while
# curl's retry timer is below KICAD_KEY_TIMEOUT s (--retry-max-time). With --retry 3 curl waits 1, 2,
# then 4 s (curl 8.5.0's manual, --retry and --retry-max-time): 20 + 4 + 20 = 44 s an address at most,
# 88 s for both. The key is 1 small file: the passing run fetched it in 0.6 s (job 134941364976).
KICAD_KEY_TIMEOUT="20"
# apt's Err: and Ign: lines name the file and the host that failed: a cut download shows them. Its
# "Need to get <size> of archives." line is the size the watch judges a pass by.
APT_PROGRESS='^((Get|Err|Ign):[0-9]+|Setting up|Unpacking|Need to get) '

FREEROUTING_VERSION="${FREEROUTING_VERSION:-1.9.0}"
FREEROUTING_SHA256="${FREEROUTING_SHA256:-9084a4888937a7f31f857ecc12aa7a37407f51160e4d2892dff9c9bb47ae3102}"
FREEROUTING_URL="${FREEROUTING_URL:-https://github.com/freerouting/freerouting/releases/download/v${FREEROUTING_VERSION}/freerouting-${FREEROUTING_VERSION}.jar}"
REQUIRE_FREEROUTING="${REQUIRE_FREEROUTING:-0}"
SKIP_APT="${SKIP_APT:-0}"

# The second router, `workcenter design --route --router freerouting2`, opt-in. FreeRouting 2.5.0's
# classes are of version 69 (the header of app/freerouting/Freerouting.class in the jar); the apt Java
# 21 reads up to 65, so it runs on its own Eclipse Temurin 25 JRE under WC_ROOT/java25. The SHA256 of
# the jar is of the file the release URL served on 2026-11-17 (64599107 bytes); the JRE's is the
# checksum api.adoptium.net publishes for that package.
INSTALL_FREEROUTING2="${INSTALL_FREEROUTING2:-0}"
REQUIRE_FREEROUTING2="${REQUIRE_FREEROUTING2:-0}"
FREEROUTING2_VERSION="2.5.0"
FREEROUTING2_SHA256="f6f51bb02245e8e717f9359bd260cc9c5c0b1bc0acc8b7cb2cd5b8ffeb5de3c7"
FREEROUTING2_URL="https://github.com/freerouting/freerouting/releases/download/v${FREEROUTING2_VERSION}/freerouting-${FREEROUTING2_VERSION}.jar"
JAVA25_VERSION="25.0.5+8"
JAVA25_SHA256="6fac98f0c8202efc3135a9e9e42aa61963ec42d1c5cbb40caf231e7b14a24ef6"
JAVA25_URL="https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.5%2B8/OpenJDK25U-jre_x64_linux_hotspot_25.0.5_8.tar.gz"

# openEMS, the field solver of `workcenter fields`. Ubuntu 24.04 has no openems package; Debian 12's
# build runs on Ubuntu 24.04's libraries. Its 4 packages are unpacked under WC_ROOT/openems, each
# checked against the SHA256 of Debian's bookworm index, and run as a separate program (GPL: none of
# its code is in this repository). REQUIRE_OPENEMS=1 makes a failed step fatal.
OPENEMS_VERSION="0.0.35+git20190103.6a75e98+dfsg.1-3.2"
OPENEMS_POOL="${OPENEMS_POOL:-https://deb.debian.org/debian/pool/main/o/openems}"
OPENEMS_DEBS=(
  "libcsxcad0 58f7143061d5c908c997999dc8bdfa732a16061c03c3251335c1788e4130f25b"
  "libnf2ff0 48e32c547caa77287a7865e07b771291198b4d76e37969dda1d6864683644053"
  "libopenems0 57b8efab419adab9e1adec4869307614ab24000e239efd4b61b18f6363cf64d6"
  "openems b5b150ffdd3e9969b1145c82c9e547ca636c93891703f66e6eb945787e58ce95"
)
OPENEMS_LIBS=(libfparser4 libtinyxml2.6.2v5 libboost-thread1.74.0 libvtk9.1t64 libhdf5-hl-100t64)
REQUIRE_OPENEMS="${REQUIRE_OPENEMS:-0}"

# The chip engines (RTL to a GDSII layout), opt-in. Every download is pinned: Ubuntu's own packages,
# micromamba by its SHA256, the conda packages by URL and MD5 in environment/chip/*.explicit.txt,
# ciel's Python packages by version, the process kit by its open_pdks commit. The kit is pinned to
# the Magic of layout.explicit.txt: a newer kit asks for a newer Magic and Magic then never returns.
INSTALL_CHIP="${INSTALL_CHIP:-0}"
CHIP_PACKAGES=(yosys iverilog verilator klayout bzip2)
MICROMAMBA_VERSION="2.10.0"
MICROMAMBA_URL="https://conda.anaconda.org/conda-forge/linux-64/micromamba-${MICROMAMBA_VERSION}-0.tar.bz2"
MICROMAMBA_SHA256="9a97976244929bbae28fb1fae504e74a3e7e6d1932870e3a03321f01b7fbd07b"
SKY130_COMMIT="6d4d11780c40b20ee63cc98e645307a9bf2b2ab8"

log() { printf '[install] %s\n' "$*"; }
warn() { printf '[install] WARN: %s\n' "$*" >&2; }
die() { printf '[install] ERROR: %s\n' "$*" >&2; exit 1; }

kicad10_present() {
  command -v kicad-cli >/dev/null 2>&1 && kicad-cli version 2>/dev/null | grep -q '^10\.'
}

os_codename() {
  # shellcheck source=/dev/null
  (. "$OS_RELEASE" && echo "${VERSION_CODENAME}")
}

# KiCad 10's source as `apt-cache policy` names it: the address without its last slash, and the suite.
kicad_source() {
  printf '%s %s' "${KICAD_PPA_URL%/}" "$(os_codename)"
}

# Runs $2... under `timeout $1` when a bound $1 is set, else with no total bound.
bounded() {
  local secs="$1"
  shift
  if [[ -n "$secs" ]]; then
    timeout "$secs" "$@"
  else
    "$@"
  fi
}

# Stops on a bound that is set but is not a whole number of seconds above 0, before anything runs.
apt_bounds_check() {
  local name value
  for name in APT_UPDATE_TIMEOUT APT_DOWNLOAD_TIMEOUT; do
    value="${!name}"
    if [[ -n "$value" && ! "$value" =~ ^[1-9][0-9]*$ ]]; then
      die "${name}=${value} is not a whole number of seconds above 0; set it to one, or leave ${name} unset for no bound"
    fi
  done
  # The passes and the wait: whole numbers with no leading 0 (bash reads 08 as a bad octal number). The
  # tops, 99 passes and 999 s, are no measurement: they refuse a typo, as 500 for 5 or 2000 for 20.
  if [[ ! "$APT_DOWNLOAD_TRIES" =~ ^[1-9][0-9]?$ ]]; then
    die "APT_DOWNLOAD_TRIES=${APT_DOWNLOAD_TRIES} is not a whole number of passes from 1 to 99; set it to one, or leave APT_DOWNLOAD_TRIES unset for 5"
  fi
  if [[ ! "$APT_DOWNLOAD_WAIT" =~ ^(0|[1-9][0-9]{0,2})$ ]]; then
    die "APT_DOWNLOAD_WAIT=${APT_DOWNLOAD_WAIT} is not a whole number of seconds from 0 to 999; set it to one, or leave APT_DOWNLOAD_WAIT unset for 20"
  fi
  if [[ ! "$APT_WATCH_WINDOW" =~ ^[1-9][0-9]{0,2}$ ]]; then
    die "APT_WATCH_WINDOW=${APT_WATCH_WINDOW} is not a whole number of seconds from 1 to 999; set it to one, or leave APT_WATCH_WINDOW unset for 120"
  fi
}

# 2 lines and exit 1: what failed, where, the value and apt's own line; then what to do.
stop() {
  printf '[install] ERROR: %s\n' "$1" >&2
  printf '[install] %s\n' "$2" >&2
  exit 1
}

# What a stop before the install leaves: no KiCad from this run, and the computer's own KiCad as it was.
kicad_kept() {
  local seen
  seen="$(kicad-cli version 2>/dev/null | head -n 1 || true)"
  if [[ -n "$seen" ]]; then
    printf 'This run installed no KiCad; the KiCad on this computer (%s) is unchanged.' "$seen"
  else
    printf 'This run installed no KiCad.'
  fi
}

# What to do after apt's line $1: "again later" ($2) only for a cause that passes by itself (a 5xx, a
# host that did not answer, a bound reached). The texts are apt 2.8.3's (its po/*.pot).
apt_advice() {
  case "$1" in
    *"Could not get lock"* | *"Unable to lock"* | *"Unable to acquire the dpkg frontend lock"*)
      printf 'Another apt or dpkg holds its lock (an update or an install of its own): run the script again when it has ended.' ;;
    *"\`apt-get update\` of every package source did not end within"*)
      # -qq names no source, and the update fetches every source's index: no source is blamed.
      printf '%s' "\`apt-get update\` fetches the index of every package source on this computer, and they did not all arrive within APT_UPDATE_TIMEOUT this time: run the script again later." ;;
    *" 5"[0-9][0-9]" "* | *"Temporary failure resolving"* | *"Could not connect"* \
      | *"Connection timed out"* | *"Connection failed"*)
      printf '%s' "$2" ;;
    *)
      printf 'Fix what apt said, then run the script again.' ;;
  esac
}
LATER="KiCad 10 comes from a third party's package source (Launchpad's KiCad PPA), which did not answer this time: run the script again later."

# The 5 lines install.sh writes to KICAD_SOURCES for codename $1, as every version of it has.
kicad_sources_text() {
  printf 'Types: deb\nURIs: %s\nSuites: %s\nComponents: main\nSigned-By: %s\n' \
    "$KICAD_PPA_URL" "$1" "$KICAD_KEYRING"
}

add_kicad_ppa() {
  local codename text
  codename="$(os_codename)"
  text="$(kicad_sources_text "$codename")"
  # A file at the script's path that is not what the script writes is the user's: left as it is, and
  # neither overwritten nor removed by a stop.
  if [[ -e "$KICAD_SOURCES" && "$(cat "$KICAD_SOURCES")" != "$text" ]]; then
    stop "apt: ${KICAD_SOURCES} is not the file install.sh writes for ${codename}; install.sh leaves it as it is." \
      "$(kicad_kept) Move that file out of $(dirname "$KICAD_SOURCES"), or remove it, then run the script again: install.sh writes its own there."
  fi
  install -d -m 0755 "$(dirname "$KICAD_KEYRING")"
  if [[ ! -s "$KICAD_KEYRING" ]]; then
    log "apt: fetching PPA signing key ${KICAD_PPA_FPR}"
    rm -f "${KICAD_KEYRING}.tmp"
    # curl's own error line of each address, for the stop when the key arrives from neither.
    local errors keyserver launchpad
    errors="$(mktemp)"
    # Some proxies reset every connection to the keyserver; Launchpad's API serves the same key
    # as a JSON string. Either way the fingerprint check below decides whether it is trusted.
    if ! curl -fsSL --retry 3 --retry-max-time "$KICAD_KEY_TIMEOUT" --connect-timeout 20 --max-time "$KICAD_KEY_TIMEOUT" \
      "https://keyserver.ubuntu.com/pks/lookup?op=get&options=mr&search=0x${KICAD_PPA_FPR}" 2> "$errors" \
      | gpg --dearmor -o "${KICAD_KEYRING}.tmp" || [[ ! -s "${KICAD_KEYRING}.tmp" ]]; then
      keyserver="$(tail -n 1 "$errors")"
      warn "apt: keyserver.ubuntu.com did not answer; fetching the key from api.launchpad.net"
      rm -f "${KICAD_KEYRING}.tmp"
      if ! curl -fsSL --retry 3 --retry-max-time "$KICAD_KEY_TIMEOUT" --connect-timeout 20 --max-time "$KICAD_KEY_TIMEOUT" \
        "https://api.launchpad.net/devel/~kicad/+archive/ubuntu/kicad-10.0-releases?ws.op=getSigningKeyData" 2> "$errors" \
        | python3 -c 'import json, sys; sys.stdout.write(json.load(sys.stdin))' \
        | gpg --dearmor -o "${KICAD_KEYRING}.tmp" || [[ ! -s "${KICAD_KEYRING}.tmp" ]]; then
        launchpad="$(tail -n 1 "$errors")"
        rm -f "$errors" "${KICAD_KEYRING}.tmp"
        # No key is no fingerprint: the stop says what happened, not "mismatch".
        stop "apt: the PPA signing key did not arrive from keyserver.ubuntu.com (curl said: ${keyserver:-nothing; the answer held no key}) or from api.launchpad.net (curl said: ${launchpad:-nothing; the answer held no key}); each try of each address had at most ${KICAD_KEY_TIMEOUT} s (KICAD_KEY_TIMEOUT)" \
          "$(kicad_kept) Check that this computer reaches keyserver.ubuntu.com or api.launchpad.net, then run the script again."
      fi
    fi
    rm -f "$errors"
    gpg --no-default-keyring --keyring "${KICAD_KEYRING}.tmp" --list-keys --with-colons 2>/dev/null \
      | grep -q "^fpr:::::::::${KICAD_PPA_FPR}:" \
      || die "apt: PPA key fingerprint mismatch; refusing to trust it"
    mv "${KICAD_KEYRING}.tmp" "$KICAD_KEYRING"
    chmod 0644 "$KICAD_KEYRING"
  fi
  printf '%s\n' "$text" > "$KICAD_SOURCES"
  log "apt: ${KICAD_SOURCES} written for ${codename}"
}

# `apt-get update` until the index of KiCad 10's source is there, at most KICAD_INDEX_TRIES times.
# A try is good when apt-get ends with 0 (within APT_UPDATE_TIMEOUT when it is set) and prints no W: or
# E: line that names the source. apt ends with 0 when an index failed and it only warned (job 134932219722 at
# 15:57:17), so its code alone does not tell. `--error-on=any` (APT::Update::Error-Mode, apt 2.8.3)
# would fail on any source's warning too, and then blame KiCad's. The candidate check reads the rest.
# apt names a source by its address without the last slash ("GPG error: <address> noble InRelease",
# "The repository '<address> noble Release' ..."), and with it in "Failed to fetch <address>/dists/...":
# the address is matched without it. Sets APT_SAID to apt's last line about the source, else apt's last
# E: line, else what ended the try. A source with 2 keys, or no release for this Ubuntu, is not tried
# again: neither passes by itself.
APT_SAID=""
KICAD_TRIED=0
# True when apt's line $1 is about KiCad's own source and does not pass by itself: a second key for it,
# or no release of it for this release of the system. The source serves noble, so on noble a missing
# Release file is the source's or a proxy's answer of the moment (404 for InRelease and Release), and
# is tried again. Another source's line of the same kind is the user's.
kicad_lasting() {
  case "$1" in
    *"Conflicting values set for option Signed-By regarding source ${KICAD_PPA_URL%/}"*) return 0 ;;
    *"${KICAD_PPA_URL%/} "*"does not have a Release file"*) [[ "$(os_codename)" != noble ]] ;;
    *) return 1 ;;
  esac
}
kicad_index() {
  local try out rc
  for ((try = 1; try <= KICAD_INDEX_TRIES; try++)); do
    KICAD_TRIED=$try
    log "apt: update, try ${try} of ${KICAD_INDEX_TRIES}"
    rc=0
    out="$(bounded "$APT_UPDATE_TIMEOUT" apt-get update -qq 2>&1)" || rc=$?
    if [[ -n "$out" ]]; then printf '%s\n' "$out" >&2; fi
    APT_SAID="$(grep -F "${KICAD_PPA_URL%/}" <<< "$out" | grep -E '^(W|E|Err):' | tail -n 1 || true)"
    if ((rc == 0)) && [[ -z "$APT_SAID" ]]; then
      return 0
    fi
    if ((rc == 124)) && [[ -n "$APT_UPDATE_TIMEOUT" ]]; then
      APT_SAID="nothing: \`apt-get update\` of every package source did not end within ${APT_UPDATE_TIMEOUT} s (APT_UPDATE_TIMEOUT)"
    elif [[ -z "$APT_SAID" ]]; then
      APT_SAID="$(grep -E '^E:' <<< "$out" | tail -n 1 || true)"
      APT_SAID="exit code ${rc}: ${APT_SAID:-$(tail -n 1 <<< "$out")}"
    fi
    if kicad_lasting "$APT_SAID"; then return 1; fi
    if ((try < KICAD_INDEX_TRIES)); then
      log "apt: the index of KiCad 10's source is not there yet; waiting ${KICAD_INDEX_WAIT} s"
      sleep "$KICAD_INDEX_WAIT"
    fi
  done
  return 1
}

# The stop after kicad_index, with what to do read from apt's line. The script's own sources file, when
# it breaks every `apt update` (a second key for the source, a release the source does not serve), is
# removed; add_kicad_ppa has stopped before on a file at that path that is not the script's.
kicad_index_stop() {
  local first file others="" tries="tries" lasting="" keys other parts list
  if ((KICAD_TRIED == 1)); then tries="try"; fi
  first="apt: the index of KiCad 10's package source did not arrive in ${KICAD_TRIED} ${tries}: $(kicad_source); apt said: ${APT_SAID}"
  if kicad_lasting "$APT_SAID"; then lasting="$APT_SAID"; fi
  case "$lasting" in
    *"Conflicting values set for option Signed-By"*)
      # apt's line ends "<source> <suite>: <key> != <key>": the other key is the one that is not ours.
      keys="${APT_SAID##*: }"
      other="$keys"
      if [[ "${keys%% != *}" == "$KICAD_KEYRING" ]]; then other="${keys##* != }"; fi
      if [[ "${keys##* != }" == "$KICAD_KEYRING" ]]; then other="${keys%% != *}"; fi
      # The entries apt reads: sources.list, then *.list and *.sources beside the script's file; a
      # commented line, and a file of another name (*.save), are not read.
      parts="$(dirname "$KICAD_SOURCES")"
      list="${parts%/*}/sources.list"
      for file in "$list" "$parts"/*.list "$parts"/*.sources; do
        if [[ -f "$file" && "$file" != "$KICAD_SOURCES" ]] \
          && grep -v '^[[:space:]]*#' "$file" | grep -F "${KICAD_PPA_URL%/}" > /dev/null; then
          others+="${others:+, }${file}"
        fi
      done
      rm -f "$KICAD_SOURCES"
      stop "$first" "Another entry names KiCad 10's package source with another key (${other}): ${others:-none found in ${list} or ${parts}/*.list, *.sources}. install.sh's own ${KICAD_SOURCES} was removed. Remove that entry, then run the script again. $(kicad_kept)" ;;
    *"does not have a Release file"*)
      rm -f "$KICAD_SOURCES"
      stop "$first" "KiCad 10's package source serves no release for $(os_codename) (${OS_RELEASE}); install.sh is for Ubuntu 24.04 (noble). install.sh's own ${KICAD_SOURCES} was removed. $(kicad_kept)" ;;
  esac
  case "$APT_SAID" in
    *"${KICAD_PPA_URL%/} "*"does not have a Release file"*)
      file="${KICAD_PPA_URL#*://}"
      stop "$first" "$(kicad_kept) KiCad 10's package source, or a proxy on the way to it, served no Release file for noble: check that this computer reaches ${file%%/*}, then run the script again." ;;
    *)
      stop "$first" "$(kicad_kept) $(apt_advice "$APT_SAID" "$LATER")" ;;
  esac
}

# For each KiCad package: `name|candidate|archive|source's version`. `apt-cache policy` prints
# "  Candidate: <version>" and, under "Version table:", each version, then 1 line per archive that has
# it ("        500 <address> <suite>/<component> <arch> Packages"; tests/samples/install/policy-ppa.txt).
# The archive is KiCad 10's source when it has the candidate, else the first other archive that does.
# The source's version is the first version KiCad 10's source has, candidate or not. The program holds
# no `|`, `>` or `||` outside its texts and patterns: the tests' fence refuses an awk that could write.
kicad_candidates() {
  apt-cache policy "${KICAD_PACKAGES[@]}" | awk -v src="$(kicad_source)" '
    function done() { if (pkg != "") print pkg "|" cand "|" from "|" own }
    /^[^ ].*:$/ { done(); pkg = substr($0, 1, length($0) - 1); cand = ""; from = ""; ver = ""; own = ""; next }
    /^  Candidate: / { cand = $2; next }
    /^ (\*\*\*|   ) [^ ]+ [0-9]+$/ { ver = $(NF - 1); next }
    /^        [0-9]+ / && ver != "" {
      line = $0; sub(/^ +[0-9]+ /, "", line); sub(/ [^ ]+ Packages$/, "", line)
      if (own == "" && index(line, src) == 1) own = ver
      if (ver != cand) next
      if (index(line, src) == 1) from = line
      else if (from == "" && line != "/var/lib/dpkg/status") from = line
    }
    END { done() }'
}

# Stops unless every KiCad package's candidate is 10.x from KiCad 10's source: apt must never install
# Ubuntu's own KiCad (7.0.11 in job 134932219722). A pin of the source would do it too, but it stays
# on the user's computer after the script and says only "no installation candidate". When the source
# has a 10.x the candidate is not, a pin or another source outranks it, and the stop says so.
kicad_candidates_check() {
  local rows pkg row cand from own src errors advice rc=0 outranked=0 bad=()
  src="$(kicad_source)"
  errors="$(mktemp)"
  rows="$(kicad_candidates 2> "$errors")" || rc=$?
  cat "$errors" >&2
  if ((rc != 0)); then
    APT_SAID="$(grep -m1 '^E:' "$errors" || true)"
    rm -f "$errors"
    stop "apt: \`apt-cache policy ${KICAD_PACKAGES[*]}\` ended with exit code ${rc}; apt said: ${APT_SAID:-nothing}" \
      "$(kicad_kept) $(apt_advice "$APT_SAID" "$LATER")"
  fi
  rm -f "$errors"
  for pkg in "${KICAD_PACKAGES[@]}"; do
    row="$(grep -F "${pkg}|" <<< "$rows" | grep -E "^${pkg}\|" || true)"
    IFS='|' read -r _ cand from own <<< "$row"
    if [[ -z "$cand" || "$cand" == "(none)" ]]; then
      if [[ "$own" == 10.* ]]; then outranked=1; fi
      bad+=("${pkg} (apt has none)")
    elif [[ "$cand" == 10.* && "$from" == "$src"* ]]; then
      continue
    elif [[ "$own" == 10.* ]]; then
      outranked=1
      bad+=("${pkg} (apt prefers ${cand} from ${from:-no archive} to the source's ${own})")
    else
      bad+=("${pkg} (apt has ${cand} from ${from:-no archive})")
    fi
  done
  if ((${#bad[@]})); then
    if ((outranked)); then
      advice="A pin (apt_preferences) or another package source outranks KiCad 10's package source; \`apt-cache policy kicad\` shows which. Remove it, then run the script again."
    else
      advice="KiCad 10 comes from a third party's package source (Launchpad's KiCad PPA), which does not offer every package as 10.x now: run the script again later."
    fi
    stop "apt: not every KiCad package's candidate is 10.x from KiCad 10's package source: $(printf '%s, ' "${bad[@]}" | sed 's/, $//'): ${src}; apt said: ${APT_SAID:-nothing about this source}" \
      "$(kicad_kept) ${advice}"
  fi
  log "apt: every KiCad package's candidate is 10.x from ${src}"
}

# Runs a command with its progress lines shown as they come (M86: the filters flush each line, and tee
# does not buffer), and returns the command's own exit code: grep ends with 1 when no line matches, as
# when every package is installed already. Call it as `apt_shown ... || rc=$?`. apt prints its W: and
# E: lines on stderr when it has fetched what it could; they are shown after the progress, as apt
# printed them. APT_SAID keeps apt's first E: line, else its last Err: line (a cut download prints no
# E: line). APT_FETCH_SAID keeps apt's first `E: Failed to fetch` line, and APT_FETCH_COUNT the number of
# them: apt prints 1 for each file it did not get (apt 2.8.3, apt-private/private-download.cc:117).
apt_shown() {
  local codes errors shown
  errors="$(mktemp)"
  shown="$(mktemp)"
  "$@" 2> "$errors" | grep --line-buffered -E "$APT_PROGRESS" | sed -u 's/^/[apt] /' | tee "$shown"
  codes=("${PIPESTATUS[@]}")
  cat "$errors" >&2
  APT_FETCH_SAID="$(grep -m1 '^E: Failed to fetch ' "$errors" || true)"
  APT_FETCH_COUNT="$(grep -c '^E: Failed to fetch ' "$errors" || true)"
  APT_SAID="$(grep -m1 '^E:' "$errors" || true)"
  if [[ -z "$APT_SAID" ]]; then
    APT_SAID="$(grep -E '^\[apt\] Err:' "$shown" | tail -n 1 | sed 's/^\[apt\] //' || true)"
  fi
  # For the download's watch and stops: the hosts of this run, and its lines kept in apt_download's file.
  APT_PASS_HOSTS="$(apt_hosts names "$shown")"
  if [[ -n "${passlog:-}" ]]; then
    cat "$shown" >> "$passlog"
  fi
  rm -f "$errors" "$shown"
  return "${codes[0]}"
}

# The bytes in apt's archives folder and its partial/: the files of a download, finished or coming.
archive_bytes() {
  { find "$APT_ARCHIVES" -maxdepth 2 -type f -printf '%s\n' 2> /dev/null || true; } \
    | awk '{ s += $1 } END { printf "%.0f\n", s }'
}

# The bytes of the first size of apt's first "Need to get <size>[/<size>] of archives." line in file $1
# (what that run of apt fetches), read as apt writes sizes (SizeToStr: SI units); empty when there is none.
need_bytes() {
  awk '$1 == "[apt]" && $2 == "Need" && $3 == "to" && $4 == "get" {
      m = 1; u = substr($6, 1, 1)
      if (u == "k") m = 1e3
      if (u == "M") m = 1e6
      if (u == "G") m = 1e9
      printf "%.0f\n", ($5 + 0) * m
      exit
    }' "$1"
}

# The hosts of the Get:, Ign: and Err: lines in file $2, the most Get: lines first: with $1 = names,
# their names; else each with its 3 counts.
apt_hosts() {
  awk -v mode="$1" '
    $1 == "[apt]" && $2 ~ /^(Get|Ign|Err):[0-9]+$/ && $3 ~ /^[a-z+]+:\/\// {
      k = substr($2, 1, 3)
      h = $3
      sub(/^[a-z+]+:\/\//, "", h)
      sub(/[\/:].*$/, "", h)
      if (!(h in seen)) { n++; order[n] = h; seen[h] = 1 }
      c[h "," k]++
    }
    END {
      for (j = 1; j <= n; j++) {
        b = 0
        for (i = 1; i <= n; i++) {
          if (i in done) continue
          if (b == 0) b = i
          else if (c[order[b] ",Get"] < c[order[i] ",Get"]) b = i
        }
        done[b] = 1
        h = order[b]
        if (mode == "names") printf "%s%s", (j == 1 ? "" : " "), h
        else printf "%s%s (%d Get, %d Ign, %d Err)", (j == 1 ? "" : ", "), h, c[h ",Get"], c[h ",Ign"], c[h ",Err"]
      }
    }' "$2"
}

# A number of bytes as apt writes sizes (SI units), cut to 1 decimal.
human() {
  local b="$1"
  if ((b < 1000)); then
    printf '%s B' "$b"
  elif ((b < 1000000)); then
    printf '%s.%s kB' "$((b / 1000))" "$((b % 1000 / 100))"
  elif ((b < 1000000000)); then
    printf '%s.%s MB' "$((b / 1000000))" "$((b % 1000000 / 100000))"
  else
    printf '%s.%s GB' "$((b / 1000000000))" "$((b % 1000000000 / 100000000))"
  fi
}

# Milliseconds of the clock.
clock() {
  printf '%s\n' "$((${EPOCHREALTIME/[.,]/} / 1000))"
}

# Runs $2... under `timeout $1` and watches it (APT_WATCH_WINDOW above); with no bound $1 it runs $2...
# alone, as before. The watch reads apt's lines from `shown`, apt_shown's file, and when it ends the pass
# it writes what it saw to `watch`, apt_download's file: "<s> <bytes> <need> <bytes/s> <rest> <s left>".
# The command runs in a process substitution: its pid is known, its output goes where apt_shown's pipe
# goes, and its end closes the pipe the watch waits on, which wakes the watch at once.
apt_watched() {
  local secs="$1" out wake pid rc=0 r=0 began now base got need rest rate left back i tick cut=0 gain span
  local -a at had
  shift
  if [[ -z "$secs" ]]; then
    "$@"
    return
  fi
  exec {out}>&1
  # The pipe stays open in the command as the descriptor `keep` names, until the command ends.
  # shellcheck disable=SC2034
  exec {wake}< <(exec {keep}>&1 >&"$out"; exec timeout "$secs" "$@")
  pid=$!
  exec {out}>&-
  # GNU timeout puts itself and apt in a process group of their own: Ctrl-C reaches the watch, not them.
  # A signal that ends the watch ends the command first.
  trap 'kill -TERM "$pid" 2> /dev/null; exit 130' INT
  trap 'kill -TERM "$pid" 2> /dev/null; exit 143' TERM
  trap 'kill -TERM "$pid" 2> /dev/null; exit 129' HUP
  began="$(clock)"
  base="$(archive_bytes)"
  at=("$began")
  had=(0)
  tick=$((APT_WATCH_WINDOW * 1000 / 24))
  while :; do
    r=0
    read -r -t "$((tick / 1000)).$(printf '%03d' "$((tick % 1000))")" -u "$wake" _ || r=$?
    if ((r <= 128)); then
      break
    fi
    if ((cut)); then
      continue
    fi
    now="$(clock)"
    got=$(($(archive_bytes) - base))
    at+=("$now")
    had+=("$got")
    need="$(need_bytes "$shown")"
    if [[ -z "$need" ]] || ((now - began < APT_WATCH_WINDOW * 1000)); then
      continue
    fi
    rest=$((need - got))
    if ((rest <= 0)); then
      continue
    fi
    back=0
    for i in "${!at[@]}"; do
      if ((at[i] <= now - APT_WATCH_WINDOW * 1000)); then
        back=$i
      fi
    done
    gain=$((got - had[back]))
    span=$((now - at[back]))
    rate=$((gain * 1000 / span))
    span=$((now - began))
    left=$((secs - span / 1000))
    if ((rate * left < rest)); then
      cut=1
      printf '%s %s %s %s %s %s\n' "$((span / 1000))" "$got" "$need" "$rate" "$rest" "$left" > "$watch"
      kill -TERM "$pid" 2> /dev/null || true
    fi
  done
  exec {wake}<&-
  wait "$pid" || rc=$?
  trap - INT TERM HUP
  return "$rc"
}

# What a computer and an image build keep of a stopped download: a failed step of `docker build` keeps
# no file it fetched.
KEPT="On a computer, apt keeps the files it has downloaded and asks only for the rest; an image build keeps none from a failed step."

# "1 pass" or "<n> passes" of APT_DOWNLOAD_TRIES.
passes_made() {
  if (($1 == 1)); then printf '1 pass of %s' "$APT_DOWNLOAD_TRIES"; else printf '%s passes of %s' "$1" "$APT_DOWNLOAD_TRIES"; fi
}

# The download of the packages $@ into apt's cache, nothing installed: up to APT_DOWNLOAD_TRIES passes,
# APT_DOWNLOAD_WAIT s apart. A pass is made again only when the one before failed because a source did
# not serve a file: under --download-only apt-get then prints 1 `E: Failed to fetch <address>  <reason>`
# line per file (apt 2.8.3, apt-private/private-download.cc:117), then `E: Some files failed to
# download` (apt-private/private-install.cc:399), and ends with 100 (apt-private/private-cmndline.cc:605).
# Its Ign: and Err: progress lines (apt-private/acqprogress.cc:130 and :139) come before and decide
# nothing here. Any other end of a pass stops at once. Each pass asks apt again: apt, not the
# script, knows which files are there. APT_DOWNLOAD_TIMEOUT, when set, is the bound of all passes and
# waits together: each pass gets what is left of it, a pass's time and the wait after it are taken from
# what is left, and a wait starts only when at least 1 s is left after it. When it is not, the stop says
# so and keeps the advice for apt's line: the bound has not ended and the line need not be slow. The
# shell counts whole seconds, so a pass of 1.9 s can count as 1 s: the passes can overrun the bound by
# less than 1 s each.
#
# With APT_DOWNLOAD_TIMEOUT set, each pass is watched (apt_watched): a pass too slow to finish in what
# is left of the bound is ended, its line says what arrived from which host at what rate, and the next
# pass follows after the wait, as for a file not served. Before it, APT_SLOW_PASS_COMMAND, when set, runs
# with the hosts of the slow pass: CI's names a mode of tools/ci/apt_archive.sh that puts the host that
# served it last in the mirror list, so that the next pass asks another host first. A stop of a bounded
# download names the hosts asked, the bytes that arrived of the bytes apt named, the time and the rate.
apt_download() {
  local pass left="$APT_DOWNLOAD_TIMEOUT" rc files began start base=0 watch passlog
  local took got need rate rest gone needs hooked=0 hosts_said rated
  local -a hook hosts
  local later="A package source did not serve a file this time: run the script again later. ${KEPT}"
  watch="$(mktemp)"
  passlog="$(mktemp)"
  start="$(clock)"
  if [[ -n "$APT_DOWNLOAD_TIMEOUT" ]]; then
    base="$(archive_bytes)"
  fi
  for ((pass = 1; ; pass++)); do
    rc=0
    began=$SECONDS
    : > "$watch"
    apt_shown apt_watched "$left" apt-get install -y --no-install-recommends --download-only \
      -o Acquire::Retries="$APT_FILE_RETRIES" \
      -o Acquire::http::Timeout="$APT_FILE_TIMEOUT" -o Acquire::https::Timeout="$APT_FILE_TIMEOUT" \
      "$@" || rc=$?
    if ((rc == 0)); then
      rm -f "$watch" "$passlog"
      return 0
    fi
    if ((rc == 124)) && [[ -n "$APT_DOWNLOAD_TIMEOUT" ]]; then
      download_cut "$pass"
    fi
    if [[ -s "$watch" ]]; then
      read -r took got need rate rest gone < "$watch"
      left=$((left - (SECONDS - began)))
      if ((pass >= APT_DOWNLOAD_TRIES || left <= APT_DOWNLOAD_WAIT)); then
        download_stop "apt: the download stopped after $(passes_made "$pass"): pass ${pass} was too slow to finish within what was left of APT_DOWNLOAD_TIMEOUT=${APT_DOWNLOAD_TIMEOUT} s; $(download_seen); apt said: ${APT_SAID:-nothing}" \
          "No package was installed. ${SLOW_LINE}"
      fi
      left=$((left - APT_DOWNLOAD_WAIT))
      needs="at that rate the rest never arrives"
      if ((rate > 0)); then needs="at that rate the rest needs $((rest / rate)) s"; fi
      hosts=()
      read -r -a hosts <<< "$APT_PASS_HOSTS"
      hosts_said="${APT_PASS_HOSTS// /, }"
      hosts_said="${hosts_said:-no host}"
      rated="$(human "$rate")"
      log "apt: download pass ${pass} of ${APT_DOWNLOAD_TRIES} was too slow to finish: $(human "$got") of $(human "$need") arrived in ${took} s, ${rated}/s over the last ${APT_WATCH_WINDOW} s from ${hosts_said}; ${needs}, and ${gone} s were left; waiting ${APT_DOWNLOAD_WAIT} s"
      if [[ -n "$APT_SLOW_PASS_COMMAND" ]]; then
        read -r -a hook <<< "$APT_SLOW_PASS_COMMAND"
        log "apt: APT_SLOW_PASS_COMMAND: ${APT_SLOW_PASS_COMMAND}${APT_PASS_HOSTS:+ ${APT_PASS_HOSTS}}"
        hooked=0
        command -- "${hook[@]}" "${hosts[@]}" || hooked=$?
        if ((hooked != 0)); then
          warn "apt: APT_SLOW_PASS_COMMAND ended with exit code ${hooked}; the next pass asks the hosts in the order they had"
        fi
      fi
      sleep "$APT_DOWNLOAD_WAIT"
      continue
    fi
    if ((rc != 100 || APT_FETCH_COUNT == 0 || pass >= APT_DOWNLOAD_TRIES)); then
      download_stop "apt: the download ended with apt-get's exit code ${rc} after $(passes_made "$pass")${APT_DOWNLOAD_TIMEOUT:+, within its bound of ${APT_DOWNLOAD_TIMEOUT} s}; apt said: ${APT_SAID:-nothing}" \
        "No package was installed. $(apt_advice "$APT_SAID" "$later")"
    fi
    if [[ -n "$APT_DOWNLOAD_TIMEOUT" ]]; then
      left=$((left - (SECONDS - began)))
      if ((left <= APT_DOWNLOAD_WAIT)); then
        download_stop "apt: the download stopped after $(passes_made "$pass"): the next wait of ${APT_DOWNLOAD_WAIT} s would leave no time for another pass within APT_DOWNLOAD_TIMEOUT=${APT_DOWNLOAD_TIMEOUT} s; apt said: ${APT_SAID:-nothing}" \
          "No package was installed. $(apt_advice "$APT_SAID" "$later")"
      fi
      left=$((left - APT_DOWNLOAD_WAIT))
    fi
    files="files"
    if ((APT_FETCH_COUNT == 1)); then files="file"; fi
    log "apt: download pass ${pass} of ${APT_DOWNLOAD_TRIES} failed on ${APT_FETCH_COUNT} ${files}; apt said: ${APT_FETCH_SAID}; waiting ${APT_DOWNLOAD_WAIT} s"
    sleep "$APT_DOWNLOAD_WAIT"
  done
}

# What a bounded download saw, for its stops (apt_download's locals): the hosts asked with their Get:,
# Ign: and Err: lines, the bytes that arrived of the bytes apt named in its first pass, the time, the rate.
download_seen() {
  local hosts got need ms text rated
  hosts="$(apt_hosts counts "$passlog")"
  got=$(($(archive_bytes) - base))
  if ((got < 0)); then got=0; fi
  need="$(need_bytes "$passlog")"
  ms=$(($(clock) - start))
  text="no host was asked for a file"
  if [[ -n "$hosts" ]]; then text="hosts asked: ${hosts}"; fi
  text+="; $(human "$got")${need:+ of $(human "$need")} arrived in $((ms / 1000)) s"
  if ((got > 0 && ms > 0)); then
    rated="$(human "$((got * 1000 / ms))")"
    text+=", ${rated}/s"
  fi
  if [[ -z "$need" ]]; then text+=", of a size apt did not name"; fi
  printf '%s' "$text"
}

# A stop of the download: its 2 files go first.
download_stop() {
  rm -f "$watch" "$passlog"
  stop "$@"
}

# The advice after a download that was too slow or cut by its bound.
SLOW_LINE="Run the script again. ${KEPT} On a slow line, give it more seconds: sudo env APT_DOWNLOAD_TIMEOUT=<seconds> ./install.sh (sudo drops a variable set before it)."

# The stop when `timeout` cut pass $1 at what was left of APT_DOWNLOAD_TIMEOUT (code 124).
download_cut() {
  download_stop "apt: the download did not end within ${APT_DOWNLOAD_TIMEOUT} s (APT_DOWNLOAD_TIMEOUT), the bound of all its passes and waits, after $(passes_made "$1"); $(download_seen); apt said: ${APT_SAID:-nothing}" \
    "No package was installed. ${SLOW_LINE}"
}

step_apt() {
  apt_bounds_check
  if [[ "$SKIP_APT" == "1" ]]; then
    log "apt: skipped (SKIP_APT=1)"
    return
  fi
  export DEBIAN_FRONTEND=noninteractive
  # The step reads apt's lines, so apt speaks in the C locale whatever the user's language: in apt
  # 2.8.3's de.po, "  Candidate: " is "  Installationskandidat: " and "Get:" is "Holen:". Only here.
  local -x LC_ALL=C
  local packages=("${BASE_PACKAGES[@]}") rc seen
  if kicad10_present; then
    log "apt: KiCad 10 present ($(kicad-cli version)); PPA step skipped"
    log "apt: update"
    # No bound here, even when APT_UPDATE_TIMEOUT is set, as before this change: CI never has KiCad 10
    # at this point, and a slow line on a computer that has it is no reason to stop.
    apt-get update -qq || die "apt: apt-get update ended with exit code $?; apt's lines are above"
  else
    add_kicad_ppa
    packages+=("${KICAD_PACKAGES[@]}")
    kicad_index || kicad_index_stop
    kicad_candidates_check
  fi
  log "apt: download ${packages[*]}"
  # Visible progress: KiCad is a large download from a PPA that can be slow; a hidden install that
  # takes 20 minutes looks hung. Both filters flush each line: into a pipe grep and sed buffer 4 KB,
  # which hid every line for 50 minutes (M86). A stalled server is given up after APT_FILE_TIMEOUT and
  # retried, where the default waited on it. The download comes first and alone, within its bound when
  # one is set: stopping it changes nothing installed. The install then reads only the downloaded files.
  apt_download "${packages[@]}"
  log "apt: install ${packages[*]}"
  rc=0
  # Non-interactive so no debconf prompt can wait on a terminal. APT::Get::Download=false is the
  # setting behind apt-get's --no-download (apt 2.8.3): nothing more is fetched.
  apt_shown apt-get install -y --no-install-recommends -o Dpkg::Options::=--force-confnew \
    -o APT::Get::Download=false "${packages[@]}" || rc=$?
  ((rc == 0)) || die "apt: the install from the downloaded files ended with apt-get's exit code ${rc}; apt said: ${APT_SAID:-nothing}"
  # The backstop: whatever apt said, the KiCad on PATH must be 10.x.
  if ! kicad10_present; then
    seen="$(kicad-cli version 2>/dev/null | head -n 1 || true)"
    die "apt: after the install \`kicad-cli version\` prints ${seen:-nothing}, not 10.x"
  fi
  # FreeRouting draws its window under xvfb, so Java needs its X11 library, lib/libawt_xawt.so. Neither
  # Ubuntu's headless runtime (its file list names libawt.so and libawt_headless.so) nor Debian's (the
  # base of the official KiCad image) has it; the full runtime, openjdk-21-jre, adds it. The library
  # counts only in the JVM of the 21 that the java step records: in CI run 44515796762 a JDK of the
  # runner's own under JVM_DIR had one, nothing more was installed, and every route ended in exit 1.
  if ! jvm21_draws; then
    log "apt: install openjdk-21-jre (the JVM of the 21 under ${JVM_DIR} has no lib/libawt_xawt.so, which FreeRouting needs)"
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openjdk-21-jre \
      | grep --line-buffered -E '^(Setting up) ' | sed -u 's/^/[apt] /' || true
    jvm21_draws \
      || die "lib/libawt_xawt.so not found in ${JVM_DIR}/java-21-openjdk-* after installing openjdk-21-jre: FreeRouting cannot run"
  fi
  log "apt: done; kicad-cli $(kicad-cli version)"
}

# A bare Ubuntu 24.04 (the container image's base) has no curl, gpg or certificates, which the PPA step
# fetches the key with, no git or make, which `make verify` runs, and no C compiler, which `workcenter
# mutate` builds a firmware with. GitHub's runner and the cloud environment have them: there this
# step installs nothing.
BOOT_PACKAGES=(curl gnupg ca-certificates git make gcc libc6-dev)
step_boot() {
  # main runs this step first: a typo in the apt step's numbers stops here, before apt installs anything.
  apt_bounds_check
  if [[ "$SKIP_APT" == "1" ]]; then
    return
  fi
  local missing=() tool
  for tool in curl gpg git make cc; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
  done
  [[ -s "$CA_BUNDLE" ]] || missing+=(ca-certificates)
  if [[ ${#missing[@]} -eq 0 ]]; then
    return
  fi
  log "boot: ${missing[*]} missing; apt install ${BOOT_PACKAGES[*]}"
  # As in the apt step: apt in the C locale, its progress shown, and its exit code stops the script with
  # its own E: line (a pipe's `|| true` let a failed install through to the check below).
  local -x LC_ALL=C DEBIAN_FRONTEND=noninteractive
  local rc=0
  apt_shown apt-get update -qq || rc=$?
  ((rc == 0)) || die "boot: \`apt-get update\` ended with exit code ${rc}; apt said: ${APT_SAID:-nothing}"
  apt_shown apt-get install -y --no-install-recommends -o Acquire::Retries="$APT_FILE_RETRIES" \
    "${BOOT_PACKAGES[@]}" || rc=$?
  ((rc == 0)) || die "boot: the install of ${BOOT_PACKAGES[*]} ended with apt-get's exit code ${rc}; apt said: ${APT_SAID:-nothing}"
  for tool in curl gpg git make cc; do
    command -v "$tool" >/dev/null 2>&1 || die "boot: ${tool} is not on PATH after the apt step"
  done
}

step_freerouting() {
  local dir="${WC_ROOT}/freerouting"
  local jar="${dir}/freerouting-${FREEROUTING_VERSION}.jar"
  mkdir -p "$dir"
  if [[ ! -s "$jar" ]]; then
    log "freerouting: downloading ${FREEROUTING_URL}"
    if curl -fsSL --retry 3 --connect-timeout 20 -o "${jar}.tmp" "$FREEROUTING_URL"; then
      mv "${jar}.tmp" "$jar"
    else
      rm -f "${jar}.tmp"
      if [[ "$REQUIRE_FREEROUTING" == "1" ]]; then
        die "freerouting: download failed and REQUIRE_FREEROUTING=1"
      fi
      warn "freerouting: download failed; the autoroute engine is unavailable until the JAR is placed at ${jar}"
      return
    fi
  fi
  if [[ -n "$FREEROUTING_SHA256" ]]; then
    echo "${FREEROUTING_SHA256}  ${jar}" | sha256sum -c - >/dev/null \
      || die "freerouting: checksum mismatch for ${jar}"
    log "freerouting: checksum ok"
  else
    warn "freerouting: no FREEROUTING_SHA256 set; checksum not verified ($(sha256sum "$jar" | cut -d' ' -f1))"
  fi
  ln -sfn "$jar" "${dir}/freerouting.jar"
  log "freerouting: ${jar}"
}

# The java Via runs (tools/routers.py, workcenter_java): the JVM of the apt step's package
# openjdk-21-jre-headless (BASE_PACKAGES), by the path this step records in WC_ROOT/java.path, whatever
# java stands first on PATH; the java on PATH only when no such JVM is there. On GitHub's runner the first
# java on PATH is the runner's own: in CI run 44444183056 apt set up openjdk-21-jre-headless 21.0.13.1,
# and doctor then read `absent   java         17.0.21`. FreeRouting's Java is 21
# (ee-agent-kit/docs/ENGINES.md); doctor holds it to JAVA_MIN in tools/routers.py, the same number. The
# JVM must also draw FreeRouting's window: lib/libawt_xawt.so, which openjdk-21-jre adds (CI run
# 44515796762 recorded the headless one, and every route there ended in exit 1).
JAVA_MIN="21"

# A JVM of the 21 that can draw FreeRouting's window: it has AWT's X11 library (openjdk-21-jre's).
jvm21_draws() {
  local candidate
  for candidate in "${JVM_DIR}/java-21-openjdk-"*; do
    if [[ -f "${candidate}/lib/libawt_xawt.so" ]]; then
      return 0
    fi
  done
  return 1
}

step_java() {
  local jvm found="" said="" ran="" code unrun="" broke="" major="" what re='version "([0-9]+)'
  local nodraw="" heard=""
  # The first JVM whose java runs, names its version and can draw FreeRouting's window
  # (lib/libawt_xawt.so). On a multiarch machine the first folder in glob order can be another
  # architecture's, whose java does not run (exec gives 126).
  for jvm in "${JVM_DIR}/java-21-openjdk-"*; do
    if [[ ! -x "${jvm}/bin/java" ]]; then
      continue
    fi
    code=0
    ran="$("${JVM_DIR}/${jvm##*/}/bin/java" -version 2>&1)" || code=$?
    if ((code == 0)) && [[ "$ran" =~ $re ]]; then
      if [[ -f "${jvm}/lib/libawt_xawt.so" ]]; then
        found="${jvm}/bin/java"
        said="$ran"
        break
      fi
      if [[ -z "$nodraw" ]]; then
        nodraw="${jvm}/bin/java"
        heard="$ran"
      fi
      continue
    fi
    if [[ -z "$unrun" ]]; then
      unrun="${jvm}/bin/java"
      broke="${ran//$'\n'/ } (exit ${code})"
    fi
  done
  # None runs and draws: the first that runs is recorded all the same (Via names it when it refuses
  # it), else the first, and the step names what is wrong with it.
  if [[ -z "$found" && -n "$nodraw" ]]; then
    found="$nodraw"
    said="$heard"
  else
    nodraw=""
  fi
  if [[ -z "$found" ]]; then
    found="$unrun"
  fi
  mkdir -p "$WC_ROOT"
  if [[ -n "$found" ]]; then
    printf '%s\n' "$found" > "${WC_ROOT}/java.path"
    what="${found} (the JVM of the apt step's openjdk-21-jre-headless, recorded in ${WC_ROOT}/java.path)"
  else
    # No record: Via reads PATH, as this step says.
    rm -f "${WC_ROOT}/java.path"
    if command -v java > /dev/null 2>&1; then
      said="$(java -version 2>&1 || true)"
      what="$(command -v java) (the first java on PATH: no JVM of the apt step under ${JVM_DIR})"
    else
      what="no java (no JVM of the apt step under ${JVM_DIR}, and none on PATH)"
    fi
  fi
  if [[ "$said" =~ $re ]]; then
    major="${BASH_REMATCH[1]}"
    what+=", Java ${major}"
  elif [[ -n "$broke" ]]; then
    what+=", whose -version said: ${broke}"
  fi
  if [[ -n "$nodraw" ]]; then
    what+=", whose JVM has no lib/libawt_xawt.so: a headless runtime, which cannot draw FreeRouting's window"
  fi
  if [[ -n "$major" ]] && ((major >= JAVA_MIN)) && [[ -z "$nodraw" ]]; then
    log "java: ${what}: Via runs it"
    return 0
  fi
  what="java: Via would run ${what}; FreeRouting needs Java ${JAVA_MIN} or newer (ee-agent-kit/docs/ENGINES.md)"
  if [[ "$REQUIRE_FREEROUTING" == "1" ]]; then
    stop "${what}, and REQUIRE_FREEROUTING=1" \
      "Install openjdk-21-jre-headless and openjdk-21-jre, the apt step's packages, so that their JVM is in ${JVM_DIR} (java-21-openjdk-<arch>) with lib/libawt_xawt.so, then run the script again: install.sh records it for Via."
  fi
  warn "${what}; doctor says java is absent until \`sudo ./install.sh\` records a Java ${JAVA_MIN}"
}

openems_fail() {
  if [[ "$REQUIRE_OPENEMS" == "1" ]]; then
    die "openems: $* and REQUIRE_OPENEMS=1"
  fi
  warn "openems: $*; \`workcenter fields\` skips until \`sudo ./install.sh --openems\` succeeds"
}

step_openems() {
  local dir="${WC_ROOT}/openems" want stamp entry name sum deb banner
  want="$(printf '%s\n' "$OPENEMS_VERSION" "${OPENEMS_DEBS[@]}" | sha256sum | cut -d' ' -f1)"
  stamp="${dir}/.debs-sha256"
  if [[ "$SKIP_APT" != "1" ]]; then
    log "openems: apt install ${OPENEMS_LIBS[*]}"
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      -o Acquire::Retries=3 -o Acquire::http::Timeout=60 -o Acquire::https::Timeout=60 "${OPENEMS_LIBS[@]}" \
      | grep --line-buffered -E '^(Get:[0-9]+|Setting up|Unpacking) ' | sed -u 's/^/[apt] /' || true
  fi
  if [[ "$(cat "$stamp" 2>/dev/null)" != "$want" ]]; then
    rm -rf "${dir}/root" "${dir}/debs"
    mkdir -p "${dir}/debs" "${dir}/root" "${dir}/bin"
    for entry in "${OPENEMS_DEBS[@]}"; do
      read -r name sum <<< "$entry"
      deb="${dir}/debs/${name}_${OPENEMS_VERSION}_amd64.deb"
      log "openems: downloading ${name} ${OPENEMS_VERSION}"
      if ! curl -fsSL --retry 3 --connect-timeout 20 -o "$deb" "${OPENEMS_POOL}/${name}_${OPENEMS_VERSION}_amd64.deb"; then
        openems_fail "download of ${name} failed"
        return
      fi
      if ! echo "${sum}  ${deb}" | sha256sum -c - >/dev/null 2>&1; then
        # A file that is not the pinned one is never unpacked: openEMS stays absent and `fields` skips.
        rm -rf "${dir}/debs" "${dir}/root"
        openems_fail "checksum mismatch for ${name}_${OPENEMS_VERSION}_amd64.deb"
        return
      fi
      dpkg-deb -x "$deb" "${dir}/root"
    done
    rm -rf "${dir}/debs"
    echo "$want" > "$stamp"
  fi
  cat > "${dir}/bin/openEMS" <<EOF
#!/bin/sh
# Generated by install.sh: Debian's openEMS ${OPENEMS_VERSION}, with its own libraries.
LD_LIBRARY_PATH="${dir}/root/usr/lib/x86_64-linux-gnu\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}" exec "${dir}/root/usr/bin/openEMS" "\$@"
EOF
  chmod 0755 "${dir}/bin/openEMS"
  # With no file openEMS prints its banner and usage and exits non-zero: the banner is the check.
  banner="$("${dir}/bin/openEMS" 2>&1 || true)"
  if [[ "$banner" =~ openEMS\ 64bit\ --\ version\ (v[0-9.]+) ]]; then
    log "openems: ${BASH_REMATCH[1]} at ${dir}/bin/openEMS"
  else
    openems_fail "${dir}/bin/openEMS does not start: $(grep -m1 -i 'error' <<< "$banner" || echo 'no banner')"
  fi
}

freerouting2_fail() {
  if [[ "$REQUIRE_FREEROUTING2" == "1" ]]; then
    die "freerouting2: $* and REQUIRE_FREEROUTING2=1"
  fi
  warn "freerouting2: $*; \`--router freerouting2\` skips until \`sudo ./install.sh --freerouting2\` succeeds"
}

step_java25() {
  local dir="${WC_ROOT}/java25" tgz="${WC_ROOT}/java25.tar.gz.tmp"
  if [[ -x "${dir}/bin/java" && "$(cat "${dir}/.sha256" 2>/dev/null)" == "$JAVA25_SHA256" ]]; then
    log "java25: Temurin ${JAVA25_VERSION} present at ${dir}/bin/java"
    return 0
  fi
  rm -rf "$dir" "$tgz"
  mkdir -p "$dir"
  log "java25: downloading Temurin JRE ${JAVA25_VERSION} from ${JAVA25_URL}"
  if ! curl -fsSL --retry 3 --connect-timeout 20 --max-time 900 -o "$tgz" "$JAVA25_URL"; then
    rm -f "$tgz"
    freerouting2_fail "download of Temurin ${JAVA25_VERSION} failed"
    return 1
  fi
  if ! echo "${JAVA25_SHA256}  ${tgz}" | sha256sum -c - >/dev/null 2>&1; then
    # A file that is not the pinned one is never unpacked: the second router stays absent.
    rm -f "$tgz"
    freerouting2_fail "checksum mismatch for Temurin ${JAVA25_VERSION}"
    return 1
  fi
  log "java25: checksum ok"
  tar -xzf "$tgz" -C "$dir" --strip-components=1
  rm -f "$tgz"
  echo "$JAVA25_SHA256" > "${dir}/.sha256"
  log "java25: $("${dir}/bin/java" -version 2>&1 | grep -m1 ' version ') at ${dir}/bin/java"
}

step_freerouting2() {
  local dir="${WC_ROOT}/freerouting2"
  local jar="${dir}/freerouting-${FREEROUTING2_VERSION}.jar"
  mkdir -p "$dir"
  if [[ ! -s "$jar" ]]; then
    log "freerouting2: downloading ${FREEROUTING2_URL}"
    if ! curl -fsSL --retry 3 --connect-timeout 20 --max-time 900 -o "${jar}.tmp" "$FREEROUTING2_URL"; then
      rm -f "${jar}.tmp"
      freerouting2_fail "download failed"
      return 1
    fi
    if ! echo "${FREEROUTING2_SHA256}  ${jar}.tmp" | sha256sum -c - >/dev/null 2>&1; then
      rm -f "${jar}.tmp"
      freerouting2_fail "checksum mismatch for freerouting-${FREEROUTING2_VERSION}.jar"
      return 1
    fi
    mv "${jar}.tmp" "$jar"
  fi
  if ! echo "${FREEROUTING2_SHA256}  ${jar}" | sha256sum -c - >/dev/null 2>&1; then
    freerouting2_fail "checksum mismatch for ${jar}"
    return 1
  fi
  log "freerouting2: checksum ok"
  ln -sfn "$jar" "${dir}/freerouting.jar"
  log "freerouting2: ${jar}, run by ${WC_ROOT}/java25/bin/java"
}

step_python() {
  local venv="${WC_ROOT}/venv"
  if [[ ! -x "${venv}/bin/python" ]] || ! grep -q '^include-system-site-packages = true' "${venv}/pyvenv.cfg"; then
    log "python: creating venv at ${venv} (sees the system packages: KiCad's pcbnew module)"
    python3 -m venv --system-site-packages "$venv"
  fi
  log "python: installing requirements.txt into venv"
  "${venv}/bin/pip" install -q --upgrade pip
  "${venv}/bin/pip" install -q -r "${SRC_DIR}/requirements.txt"
  log "python: $("${venv}/bin/python" --version), $("${venv}/bin/pip" list --format=freeze 2>/dev/null | grep -Ei '^(kicad-python|pytest|ruff)=' | tr '\n' ' ')"
}

step_link() {
  mkdir -p "$WC_ROOT"
  ln -sfn "${SRC_DIR}/tools/workcenter" "$WORKCENTER_LINK"
  install -m 0644 "${SRC_DIR}/WORKCENTER.md" "${WC_ROOT}/WORKCENTER.md"
  cat > "${WC_ROOT}/env.sh" <<EOF
# Generated by install.sh. Source this to address the workcenter from a shell.
export WORKCENTER_ROOT="${WC_ROOT}"
export WORKCENTER_SRC="${SRC_DIR}"
export FREEROUTING_JAR="${WC_ROOT}/freerouting/freerouting.jar"
EOF
  log "link: ${WORKCENTER_LINK} -> ${SRC_DIR}/tools/workcenter"
  log "link: manifest at ${WC_ROOT}/WORKCENTER.md"
}

# 1 conda environment from its lock file. The stamp holds the lock's SHA256: a second run with the
# same lock downloads nothing, and a changed lock builds the environment again.
chip_env() {
  local name="$1" lock="$2" root="${WC_ROOT}/chip"
  local env="${root}/mamba/envs/${name}" want
  want="$(sha256sum "$lock" | cut -d' ' -f1)"
  if [[ -d "$env" && "$(cat "${env}/.lock-sha256" 2>/dev/null)" == "$want" ]]; then
    log "chip: ${name} environment present"
    return
  fi
  log "chip: creating the ${name} environment from $(basename "$lock")"
  rm -rf "$env"
  # HOME points inside the root: micromamba makes a package folder in the home it is given.
  HOME="${root}/mamba/home" MAMBA_ROOT_PREFIX="${root}/mamba" "${root}/mm/bin/micromamba" create --no-rc -y -q \
    -p "$env" --file "$lock" < /dev/null || die "chip: the ${name} environment failed"
  echo "$want" > "${env}/.lock-sha256"
}

step_chip() {
  local root="${WC_ROOT}/chip" locks="${SRC_DIR}/environment/chip" py="${WC_ROOT}/venv/bin/python"
  local kit="${root}/pdk/ciel/ciel/sky130/versions/${SKY130_COMMIT}/sky130A" tool want
  [[ -x "$py" ]] || py="python3"
  if [[ "$SKIP_APT" == "1" ]]; then
    log "chip: apt skipped (SKIP_APT=1)"
  else
    log "chip: apt install ${CHIP_PACKAGES[*]}"
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      -o Acquire::Retries=3 -o Acquire::http::Timeout=60 -o Acquire::https::Timeout=60 "${CHIP_PACKAGES[@]}" \
      | grep --line-buffered -E '^(Get:[0-9]+|Setting up|Unpacking) ' | sed -u 's/^/[apt] /' || true
  fi
  for tool in yosys iverilog vvp verilator klayout bzip2; do
    command -v "$tool" >/dev/null 2>&1 || die "chip: ${tool} is not on PATH after the apt step"
  done
  mkdir -p "${root}/mm" "${root}/bin" "${root}/mamba/home"
  if [[ "$("${root}/mm/bin/micromamba" --version 2>/dev/null)" != "$MICROMAMBA_VERSION" ]]; then
    log "chip: downloading micromamba ${MICROMAMBA_VERSION}"
    curl -fsSL --retry 3 --connect-timeout 20 -o "${root}/micromamba.tar.bz2" "$MICROMAMBA_URL" \
      || die "chip: micromamba download failed"
    echo "${MICROMAMBA_SHA256}  ${root}/micromamba.tar.bz2" | sha256sum -c - >/dev/null \
      || die "chip: checksum mismatch for micromamba"
    tar -xjf "${root}/micromamba.tar.bz2" -C "${root}/mm" bin/micromamba
    rm -f "${root}/micromamba.tar.bz2"
  fi
  chip_env openroad "${locks}/openroad.explicit.txt"
  chip_env layout "${locks}/layout.explicit.txt"
  HOME="${root}/mamba/home" MAMBA_ROOT_PREFIX="${root}/mamba" "${root}/mm/bin/micromamba" clean --no-rc -y --all \
    < /dev/null > /dev/null 2>&1 || true
  want="$(sha256sum "${locks}/ciel.requirements.txt" | cut -d' ' -f1)"
  if [[ "$(cat "${root}/ciel-app/.lock-sha256" 2>/dev/null)" != "$want" ]]; then
    log "chip: installing ciel from ciel.requirements.txt"
    rm -rf "${root}/ciel-app"
    "$py" -m pip install -q --no-deps --root-user-action=ignore --target "${root}/ciel-app" \
      -r "${locks}/ciel.requirements.txt" || die "chip: ciel failed to install"
    echo "$want" > "${root}/ciel-app/.lock-sha256"
  fi
  if [[ -f "${kit}/libs.tech/magic/sky130A.tech" ]]; then
    log "chip: sky130A ${SKY130_COMMIT:0:7} present"
  else
    log "chip: fetching sky130A at ${SKY130_COMMIT:0:7} (the sky130_fd_sc_hd library)"
    PYTHONPATH="${root}/ciel-app" "$py" -m ciel enable --pdk-root "${root}/pdk/ciel" --pdk-family sky130 \
      -l sky130_fd_sc_hd "$SKY130_COMMIT" < /dev/null > "${root}/ciel.log" 2>&1 \
      || die "chip: the process kit failed to install; see ${root}/ciel.log"
    [[ -f "${kit}/libs.tech/magic/sky130A.tech" ]] || die "chip: ${kit} is not there after ciel"
  fi
  # Stable names for the gates: the engines by name, the kit at its pinned commit. ciel's own
  # sky130A link moves when another version is enabled; this one names the commit above.
  ln -sfn "${root}/mamba/envs/openroad/bin/openroad" "${root}/bin/openroad"
  ln -sfn "${root}/mamba/envs/openroad/bin/sta" "${root}/bin/sta"
  ln -sfn "${root}/mamba/envs/layout/bin/magic" "${root}/bin/magic"
  ln -sfn "${root}/mamba/envs/layout/bin/netgen" "${root}/bin/netgen"
  ln -sfn "$kit" "${root}/pdk/sky130A"
  # Magic and Netgen wait on standard input when it is a terminal: every call gets /dev/null.
  "${root}/bin/openroad" -version < /dev/null > /dev/null 2>&1 || die "chip: openroad does not run"
  "${root}/bin/magic" --version < /dev/null > /dev/null 2>&1 || die "chip: magic does not run"
  "${root}/bin/netgen" -batch quit < /dev/null > /dev/null 2>&1 || die "chip: netgen does not run"
  log "chip: openroad $("${root}/bin/openroad" -version < /dev/null 2>/dev/null | head -1 | cut -c1-12)," \
      "opensta $("${root}/bin/sta" -version < /dev/null 2>/dev/null | head -1)," \
      "magic $("${root}/bin/magic" --version < /dev/null 2>/dev/null | head -1)," \
      "sky130A ${SKY130_COMMIT:0:7}, $(du -sh "$root" | cut -f1) in ${root}"
}

main() {
  if [[ "${1:-}" == "--check" ]]; then
    exec python3 "${SRC_DIR}/tools/workcenter" doctor
  fi
  [[ "$EUID" -eq 0 ]] || die "run as root (sudo ./install.sh)"
  local t0=$SECONDS
  if [[ "${1:-}" == "--chip" ]]; then
    step_chip
    log "done in $((SECONDS - t0))s"
    return
  fi
  if [[ "${1:-}" == "--openems" ]]; then
    step_openems
    log "done in $((SECONDS - t0))s"
    return
  fi
  if [[ "${1:-}" == "--freerouting2" ]]; then
    if step_java25; then step_freerouting2 || true; fi
    log "done in $((SECONDS - t0))s"
    return
  fi
  step_boot
  step_apt
  step_freerouting
  step_java
  step_openems
  step_python
  step_link
  if [[ "$INSTALL_FREEROUTING2" == "1" ]]; then
    if step_java25; then step_freerouting2 || true; fi
  fi
  if [[ "$INSTALL_CHIP" == "1" ]]; then
    step_chip
  fi
  log "done in $((SECONDS - t0))s"
  python3 "${SRC_DIR}/tools/workcenter" doctor
}

# The steps run when the script is executed, not when a test sources it to call 1 function.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
