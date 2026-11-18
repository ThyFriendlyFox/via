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
#   INSTALL_CHIP          1 also installs the chip engines and the sky130A
#                         process kit, 1.9 GB under WORKCENTER_ROOT/chip
#                         (default 0: a board needs none of them)

set -euo pipefail

WC_NAME="ee"
WC_ROOT="${WORKCENTER_ROOT:-/opt/workcenters/${WC_NAME}}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# KiCad 10 PPA, added by writing the sources file and key directly:
# add-apt-repository needs the system python's apt_pkg, which images with a
# different default python3 do not have.
KICAD_PPA_URL="https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu/"
KICAD_PPA_FPR="FDA854F61C4D0D9572BB95E5245D5502FAD7A805"   # "PPA for KiCad: 10.0 releases"
KICAD_KEYRING="/etc/apt/keyrings/kicad-10.0-releases.gpg"
KICAD_SOURCES="/etc/apt/sources.list.d/kicad-10.0-releases.sources"
KICAD_PACKAGES=(kicad kicad-symbols kicad-footprints kicad-templates)
BASE_PACKAGES=(ngspice openjdk-21-jre-headless xvfb shellcheck librsvg2-bin ffmpeg
               python3 python3-venv python3-pip curl ca-certificates)

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

add_kicad_ppa() {
  local codename
  # shellcheck source=/dev/null
  codename="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
  install -d -m 0755 /etc/apt/keyrings
  if [[ ! -s "$KICAD_KEYRING" ]]; then
    log "apt: fetching PPA signing key ${KICAD_PPA_FPR}"
    rm -f "${KICAD_KEYRING}.tmp"
    # Some proxies reset every connection to the keyserver; Launchpad's API serves the same key
    # as a JSON string. Either way the fingerprint check below decides whether it is trusted.
    if ! curl -fsSL --retry 3 --connect-timeout 20 --max-time 120 \
      "https://keyserver.ubuntu.com/pks/lookup?op=get&options=mr&search=0x${KICAD_PPA_FPR}" \
      | gpg --dearmor -o "${KICAD_KEYRING}.tmp" || [[ ! -s "${KICAD_KEYRING}.tmp" ]]; then
      warn "apt: keyserver.ubuntu.com did not answer; fetching the key from api.launchpad.net"
      rm -f "${KICAD_KEYRING}.tmp"
      curl -fsSL --retry 3 --connect-timeout 20 --max-time 120 \
        "https://api.launchpad.net/devel/~kicad/+archive/ubuntu/kicad-10.0-releases?ws.op=getSigningKeyData" \
        | python3 -c 'import json, sys; sys.stdout.write(json.load(sys.stdin))' \
        | gpg --dearmor -o "${KICAD_KEYRING}.tmp"
    fi
    gpg --no-default-keyring --keyring "${KICAD_KEYRING}.tmp" --list-keys --with-colons 2>/dev/null \
      | grep -q "^fpr:::::::::${KICAD_PPA_FPR}:" \
      || die "apt: PPA key fingerprint mismatch; refusing to trust it"
    mv "${KICAD_KEYRING}.tmp" "$KICAD_KEYRING"
    chmod 0644 "$KICAD_KEYRING"
  fi
  cat > "$KICAD_SOURCES" <<EOF
Types: deb
URIs: ${KICAD_PPA_URL}
Suites: ${codename}
Components: main
Signed-By: ${KICAD_KEYRING}
EOF
  log "apt: ${KICAD_SOURCES} written for ${codename}"
}

step_apt() {
  if [[ "$SKIP_APT" == "1" ]]; then
    log "apt: skipped (SKIP_APT=1)"
    return
  fi
  export DEBIAN_FRONTEND=noninteractive
  local packages=("${BASE_PACKAGES[@]}")
  if kicad10_present; then
    log "apt: KiCad 10 present ($(kicad-cli version)); PPA step skipped"
  else
    add_kicad_ppa
    packages+=("${KICAD_PACKAGES[@]}")
  fi
  log "apt: update"
  apt-get update -qq
  log "apt: install ${packages[*]}"
  # Visible progress: KiCad is a large download from a PPA that can be slow; a hidden install that
  # takes 20 minutes looks hung. Both filters flush each line: into a pipe grep and sed buffer 4 KB,
  # which hid every line for 50 minutes (M86). A stalled mirror gives up after 60 s and is retried,
  # where the default waited on it. Non-interactive so no debconf prompt can wait on a terminal.
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    -o Dpkg::Options::=--force-confnew -o Acquire::Retries=3 \
    -o Acquire::http::Timeout=60 -o Acquire::https::Timeout=60 "${packages[@]}" \
    | grep --line-buffered -E '^(Get:[0-9]+|Setting up|Unpacking) ' | sed -u 's/^/[apt] /' || true
  kicad10_present || die "kicad-cli 10.x not found after install"
  # FreeRouting draws its window under xvfb, so Java needs its X11 library. Ubuntu's headless
  # runtime ships libawt_xawt.so; Debian's (the base of the official KiCad image) does not, and
  # FreeRouting stops there with a HeadlessException. The full runtime carries it.
  if ! find /usr/lib/jvm -name libawt_xawt.so 2>/dev/null | grep -q .; then
    log "apt: install openjdk-21-jre (this runtime has no libawt_xawt.so, which FreeRouting needs)"
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openjdk-21-jre \
      | grep --line-buffered -E '^(Setting up) ' | sed -u 's/^/[apt] /' || true
    find /usr/lib/jvm -name libawt_xawt.so 2>/dev/null | grep -q . \
      || die "libawt_xawt.so not found after installing openjdk-21-jre: FreeRouting cannot run"
  fi
  log "apt: done; kicad-cli $(kicad-cli version)"
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
  ln -sfn "${SRC_DIR}/tools/workcenter" /usr/local/bin/workcenter
  install -m 0644 "${SRC_DIR}/WORKCENTER.md" "${WC_ROOT}/WORKCENTER.md"
  cat > "${WC_ROOT}/env.sh" <<EOF
# Generated by install.sh. Source this to address the workcenter from a shell.
export WORKCENTER_ROOT="${WC_ROOT}"
export WORKCENTER_SRC="${SRC_DIR}"
export FREEROUTING_JAR="${WC_ROOT}/freerouting/freerouting.jar"
EOF
  log "link: /usr/local/bin/workcenter -> ${SRC_DIR}/tools/workcenter"
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
  step_apt
  step_freerouting
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

main "$@"
