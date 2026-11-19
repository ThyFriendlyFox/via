#!/usr/bin/env bash
# CI's install path: apt asks Ubuntu's own archive, not the runner's regional or cloud mirror.
#
#   sudo env APT_ARCHIVE_CI=1 bash tools/ci/apt_archive.sh /etc/apt
#
# In apt's source files of a folder (the argument, else $APT_DIR, else /etc/apt), a host that is a
# mirror of Ubuntu's archive under its own name (us-east-2.ec2.archive.ubuntu.com,
# azure.archive.ubuntu.com, us.archive.ubuntu.com, <region>.clouds.archive.ubuntu.com, and the same
# under ports.ubuntu.com) becomes archive.ubuntu.com or ports.ubuntu.com. Scheme and path stay.
# security.ubuntu.com, a PPA, a third party's source, Ubuntu's own archive and comments stay as they are.
#
# The files read: sources.list, sources.list.d/*.list, sources.list.d/*.sources, and apt-mirrors.txt,
# the mirror list GitHub's ubuntu-24.04 images name as mirror+file:/etc/apt/apt-mirrors.txt
# (actions/runner-images, images/ubuntu/scripts/build/configure-apt-sources.sh). A source that names
# another mirror list, or no source file at all, is a layout this script does not know: it says so
# and changes nothing. It changes all or nothing, prints 1 line per file it changed, or 1 line that it
# changed nothing, and a second run changes nothing.
#
# It refuses this machine's own /etc/apt unless APT_ARCHIVE_CI=1 (CI's workflows set it): a person's
# computer keeps the mirror its owner chose. Exit 0 when it ran, 2 when it refused or found no folder.
set -euo pipefail
export LC_ALL=C

say() { printf '[apt-archive] %s\n' "$*"; }
stop() { printf '[apt-archive] %s\n' "$*" >&2; exit 2; }

dir="${1:-${APT_DIR:-/etc/apt}}"
real="$(realpath -m -- "$dir")"
etc="$(realpath -m -- /etc/apt)"
if [[ "$real" == "$etc" || "$real" == /etc/apt ]] && [ "${APT_ARCHIVE_CI:-}" != 1 ]; then
  stop "refused: /etc/apt is this machine's own apt folder; CI says it may change it with APT_ARCHIVE_CI=1" \
    "(.github/workflows/ci.yml); changed nothing"
fi
[[ -d "$dir" ]] || stop "no folder $dir; changed nothing"

LIST="$dir/apt-mirrors.txt"
KNOWN="mirror+file:/etc/apt/apt-mirrors.txt"
# A host of the archive's own name with at least 1 label in front: archive.ubuntu.com alone, and
# security.ubuntu.com, do not match. HOST ends as EDIT ends, so the printed line names only the hosts
# sed changed: my.archive.ubuntu.com.cn matches neither.
HOST='https?://([A-Za-z0-9-]+\.)+(archive|ports)\.ubuntu\.com([/:[:space:]]|$)'
EDIT="/^[[:space:]]*#/!s#(https?://)([A-Za-z0-9-]+\\.)+((archive|ports)\\.ubuntu\\.com)([/:[:space:]]|\$)#\\1\\3\\5#g"

files=()
for f in "$dir/sources.list" "$dir"/sources.list.d/*.list "$dir"/sources.list.d/*.sources "$LIST"; do
  if [[ -f "$f" ]]; then files+=("$f"); fi
done
if [[ "${#files[@]}" -eq 0 ]]; then
  say "no apt source file in $dir: a layout this script does not know; changed nothing"
  exit 0
fi

# Every mirror list a source names must be the 1 the images write, and it must be there.
for f in "${files[@]}"; do
  [[ "$f" == "$LIST" ]] && continue
  uris="$(grep -v '^[[:space:]]*#' -- "$f" | grep -oE '(^|[[:space:]])mirror(\+[a-z]+)?:[^[:space:]]*' || true)"
  for uri in $uris; do
    if [[ "$uri" != "$KNOWN" ]]; then
      say "$f names $uri, a mirror list this script does not know; changed nothing"
      exit 0
    fi
    if [[ ! -f "$LIST" ]]; then
      say "$f names $uri, and $LIST is absent: a layout this script does not know; changed nothing"
      exit 0
    fi
  done
done

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT

# First every new text, then the writes: a failure before the writes changes nothing.
changed=()
notes=()
n=0
for f in "${files[@]}"; do
  n=$((n + 1))
  sed -E "$EDIT" -- "$f" > "$work/$n"
  if cmp -s -- "$f" "$work/$n"; then continue; fi
  hosts="$(grep -v '^[[:space:]]*#' -- "$f" | grep -oE "$HOST" | sed -E 's#^https?://##; s#[/:[:space:]]$##' | sort -u)"
  note=""
  for h in $hosts; do
    note+="${note:+, }$h -> ${h#"${h%.*.ubuntu.com}".}"
  done
  changed+=("$f")
  notes+=("$work/$n|$note")
done

if [[ "${#changed[@]}" -eq 0 ]]; then
  say "no regional or cloud mirror of Ubuntu's archive in $dir; changed nothing"
  exit 0
fi
for i in "${!changed[@]}"; do
  # cp onto the file keeps its owner and mode.
  cp -- "${notes[$i]%%|*}" "${changed[$i]}"
  say "${changed[$i]}: ${notes[$i]#*|}"
done
