#!/usr/bin/env bash
# apt's package files kept between CI runs of the install path (ee-agent-kit/CI.md, "apt's package files
# kept between runs"). The workflow's actions/cache restores and saves a folder of the runner's user; this
# script moves the .deb files between that folder and apt's own, and says in 1 line what it did.
#
#   apt_cache.sh key <install.sh> <output file>
#       The cache's key and its fallbacks, as step outputs `key` and `restore-keys`.
#   apt_cache.sh restore <kept folder> <apt's archives folder>
#       Copies each regular .deb file of the kept folder into apt's folder, under sudo. Never fails.
#   apt_cache.sh keep <kept folder> <apt's archives folder> <output file>
#       After the install: checks every .deb in apt's folder against the SHA256 of apt's signed indexes,
#       then, for a run that saves, makes the kept folder anew from the files that match; output `save`.
#       Reads EVENT (github.event_name), INSTALLED (the install step's outcome), HIT (the restore's
#       cache-hit) and KEY. It fails only when a file's bytes are not what the index says.
#
# Why the check: apt 2.8.3 takes a file already in its archives folder by its size alone, not its hash
# (apt-pkg/acquire-item.cc:3494-3512, pkgAcqArchive), and installs it. A kept file of the right size and
# other bytes would be installed. Only runs of main's own code save (a push to main, the nightly run, a
# run by hand), and the check names such a file after the install and saves nothing.
#
# install.sh is not changed: it finds the files where apt always looks, as on a person's computer, and
# apt's download (its sandbox user _apt included) works as it does there.
set -euo pipefail

PREFIX="[apt-cache]"
OS_RELEASE="${OS_RELEASE:-/etc/os-release}"

# "ubuntu-24.04" from os-release, else "unknown".
release() {
  awk -F= '
    $1 == "ID" { gsub(/"/, "", $2); id = $2 }
    $1 == "VERSION_ID" { gsub(/"/, "", $2); v = $2 }
    END { if (id == "" || v == "") print "unknown"; else print id "-" v }' "$OS_RELEASE" 2> /dev/null \
    || echo unknown
}

# The lines of install.sh that decide which packages apt fetches and from where: each `*_PACKAGES=(`
# and `*_LIBS=(` list to its `)`, the PPA's address, and every line that runs `apt-get install`.
package_lines() {
  awk '
    /^[A-Z_]+_(PACKAGES|LIBS)=\(/ { on = 1 }
    on { print; if (/\)/) on = 0; next }
    /^KICAD_PPA_URL=/ || /apt-get install/ { print }' "$1"
}

do_key() {
  local script="$1" out="$2" hash period base key
  hash="$(package_lines "$script" | sha256sum | cut -c1-16)"
  # A new key each ISO week, so a save follows the packages as they are updated upstream.
  period="$(date -u +%G-w%V)"
  base="apt-archives-v1-${RUNNER_OS:-unknown}-${RUNNER_ARCH:-unknown}-$(release)"
  key="${base}-${hash}-${period}"
  printf 'key=%s\nrestore-keys<<APT_CACHE_KEYS\n%s\n%s\nAPT_CACHE_KEYS\n' "$key" "${base}-${hash}-" "${base}-" >> "$out"
  echo "${PREFIX} key: ${key}; without it, the newest save of ${base}-${hash}-, else of ${base}-"
}

# The sum of the sizes of the NUL-separated paths in file $1.
bytes_of() {
  { xargs -0 -r stat -c %s -- < "$1" || true; } | awk '{ s += $1 } END { printf "%.0f\n", s }'
}

do_restore() {
  local dir="$1" archives="$2" list n bytes others left=""
  if [[ ! -d "$dir" || -L "$dir" ]]; then
    echo "${PREFIX} restored 0 files: ${dir} is not there (no save of this key or its fallbacks); apt gets every file"
    return 0
  fi
  list="$(mktemp)"
  # Regular files only: find does not follow a link, so a link (to a .deb or anywhere) is left out.
  find "$dir" -mindepth 1 -maxdepth 1 -type f -name '*.deb' -print0 | sort -z > "$list"
  n="$(tr -cd '\0' < "$list" | wc -c)"
  bytes="$(bytes_of "$list")"
  others="$(find "$dir" -mindepth 1 -maxdepth 1 ! \( -type f -name '*.deb' \) -printf '%f\n' | LC_ALL=C sort)"
  if [[ -n "$others" ]]; then
    left="; left out $(wc -l <<< "$others") that are not a regular .deb file: $(paste -sd, <<< "$others" | sed 's/,/, /g')"
  fi
  if ((n > 0)) && ! xargs -0 -r sudo cp --preserve=timestamps -t "$archives" -- < "$list"; then
    rm -f "$list"
    echo "${PREFIX} restored 0 files: the copy into ${archives} failed; apt gets every file"
    return 0
  fi
  rm -f "$list"
  echo "${PREFIX} restored ${n} files, ${bytes} bytes, into ${archives}${left}"
}

# Checks each .deb of folder $1 against apt's signed indexes; writes the names that match into file $2.
# Returns 1 when a file's SHA256 is not the one its index gives.
check() {
  local archives="$1" matched="$2" names want name pkg rest ver got k=0 m=0 n=0 bad=0
  : > "$matched"
  names="$(find "$archives" -mindepth 1 -maxdepth 1 -type f -name '*.deb' -printf '%f\n' | LC_ALL=C sort)"
  local specs=()
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    pkg="${name%%_*}"
    rest="${name#*_}"
    ver="${rest%_*}"
    specs+=("${pkg}=${ver//%3a/:}")
  done <<< "$names"
  # Package_Version_Architecture.deb (the version's colon as %3a, as apt names the file) and its SHA256,
  # from the record apt shows for that version: an index's, which holds SHA256; dpkg's status file has
  # none, so a version only installed and no longer listed has no line here.
  want=""
  if ((${#specs[@]} > 0)); then
    want="$(LC_ALL=C apt-cache show "${specs[@]}" 2> /dev/null | awk '
      /^Package: / { p = $2 } /^Version: / { v = $2 } /^Architecture: / { a = $2 } /^SHA256: / { h = $2 }
      /^$/ { if (p != "" && h != "") { gsub(/:/, "%3a", v); print p "_" v "_" a ".deb " h }; p = v = a = h = "" }
      END { if (p != "" && h != "") { gsub(/:/, "%3a", v); print p "_" v "_" a ".deb " h } }' || true)"
  fi
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    n=$((n + 1))
    local expect
    expect="$(awk -v f="$name" '$1 == f { print $2; exit }' <<< "$want")"
    if [[ -z "$expect" ]]; then
      k=$((k + 1))
      continue
    fi
    got="$(sha256sum -- "${archives}/${name}" | cut -d' ' -f1)" || got="unreadable"
    if [[ "$got" != "$expect" ]]; then
      echo "${PREFIX} ${name}: SHA256 ${got}, but apt's index says ${expect}: apt took this kept file by its size and installed it; nothing is saved"
      bad=1
      continue
    fi
    m=$((m + 1))
    printf '%s\n' "$name" >> "$matched"
  done <<< "$names"
  if ((bad)); then
    return 1
  fi
  echo "${PREFIX} checked ${n} files in ${archives} against apt's signed indexes: ${m} match, ${k} that no index lists are left out"
}

do_keep() {
  local dir="$1" archives="$2" out="$3" matched n bytes list
  if [[ "${INSTALLED:-}" != success ]]; then
    echo "${PREFIX} not saved: the install step ended with ${INSTALLED:-no outcome}; only a good install saves"
    echo "save=false" >> "$out"
    return 0
  fi
  matched="$(mktemp)"
  if ! check "$archives" "$matched"; then
    rm -f "$matched"
    echo "save=false" >> "$out"
    return 1
  fi
  case "${EVENT:-}" in
    push | schedule | workflow_dispatch) ;;
    *)
      rm -f "$matched"
      echo "${PREFIX} not saved: a run of ${EVENT:-no event} restores and never saves; a push to main, the nightly run and a run by hand save"
      echo "save=false" >> "$out"
      return 0
      ;;
  esac
  if [[ "${HIT:-}" == true ]]; then
    rm -f "$matched"
    echo "${PREFIX} not saved: the restore found this key itself (${KEY:-}); a saved key cannot be written again"
    echo "save=false" >> "$out"
    return 0
  fi
  n="$(wc -l < "$matched")"
  if [[ -z "${KEY:-}" || "$n" -eq 0 ]]; then
    rm -f "$matched"
    if [[ -z "${KEY:-}" ]]; then
      echo "${PREFIX} not saved: the key step gave no key"
    else
      echo "${PREFIX} not saved: apt's folder holds no file an index lists"
    fi
    echo "save=false" >> "$out"
    return 0
  fi
  # The kept folder is made anew, so a file no index lists any more leaves the cache.
  case "$dir" in "" | / | //*) echo "${PREFIX} not saved: ${dir:-an empty name} is no folder to keep" ; echo "save=false" >> "$out"; return 0 ;; esac
  rm -rf -- "$dir"
  mkdir -p -- "$dir"
  list="$(mktemp)"
  while IFS= read -r name; do printf '%s\0' "${archives}/${name}"; done < "$matched" > "$list"
  rm -f "$matched"
  if ! xargs -0 -r cp --preserve=timestamps -t "$dir" -- < "$list"; then
    rm -f "$list"
    echo "${PREFIX} not saved: the copy from ${archives} into ${dir} failed"
    echo "save=false" >> "$out"
    return 0
  fi
  bytes="$(bytes_of "$list")"
  rm -f "$list"
  echo "${PREFIX} saving ${n} files, ${bytes} bytes, under ${KEY}"
  echo "save=true" >> "$out"
}

case "${1:-}" in
  key) do_key "$2" "$3" ;;
  restore) do_restore "$2" "$3" ;;
  keep) do_keep "$2" "$3" "$4" ;;
  *)
    echo "usage: apt_cache.sh key <install.sh> <output> | restore <kept> <archives> | keep <kept> <archives> <output>" >&2
    exit 2
    ;;
esac
