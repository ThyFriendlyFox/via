#!/usr/bin/env bash
# CI's install path: apt keeps more than 1 host for Ubuntu's archive and asks first the one that was
# fastest in a sample of 1 MiB; in `apt-get update` it gives up a host that goes silent.
#
#   sudo env APT_ARCHIVE_CI=1 bash tools/ci/apt_archive.sh /etc/apt
#   env APT_ARCHIVE_CI=1 bash tools/ci/apt_archive.sh --slow <host>...
#
# The sample is a first guess only. In CI run 44506767788 (2026-11-19) the first host sent its MiB at
# 2468910 bytes/s and, 17 s later, the download at 48.3 kB/s. install.sh watches its download passes and
# ends one too slow to finish within its bound; then it runs its APT_SLOW_PASS_COMMAND, which CI sets to
# the second form above, with the hosts of that pass, the most files first. It runs the same command
# between 2 tries of its `apt-get update` after a try its bound ended, with the hosts of the mirror list's
# sources that had printed no line. The first of them that the mirror list holds goes last, the others
# keep their order, and the priorities are written 1, 2, ...; the next pass or try asks another host first. Nothing is probed. A list that holds none of them, or no list,
# is said and left as it is. The folder is $APT_DIR, else /etc/apt.
#
# In a folder of apt's files (the argument, else $APT_DIR, else /etc/apt):
# 1. A source line that names a mirror of Ubuntu's archive under its own name
#    (us-east-2.ec2.archive.ubuntu.com, azure.archive.ubuntu.com, us.archive.ubuntu.com,
#    <region>.clouds.archive.ubuntu.com, and the same under ports.ubuntu.com) names the mirror list
#    mirror+file:/etc/apt/apt-mirrors.txt instead, and the list gets that mirror.
# 2. The list gets Ubuntu's own archive (archive.ubuntu.com, ports.ubuntu.com) beside every such mirror,
#    with the mirror's scheme and path, unless a line of that host is there.
# 3. A probe asks each host of the list for the first 1 MiB of dists/<suite>/main/binary-<arch>/Packages.gz
#    (an index every mirror of the archive has), all side by side, 3 s each (curl), ended at 4 s:
#    the step waits at most 5 s, within the 237 s CI's `full` job leaves beside install.sh's worst case
#    (tests/test_install_apt.py, the worst case of the apt step: 2163 s of 2400). The list's priorities are set by bytes a second, the fastest first;
#    a host that does not answer goes last, in the runner's order, and stays. The probe never fails the
#    step: with no answer at all the priorities stay.
# 4. apt.conf.d/80apt-archive-ci: a file whose host sends nothing for 15 s is not tried again there;
#    apt's mirror method asks the next host of the list for it. A host that accepts the connection and
#    then sends nothing costs 2 timeouts, 30 s (methods/basehttp.cc). apt fetches the files of 1 host
#    one after another (apt-pkg/acquire.cc: 1 queue per host), so the runner's 4 InRelease files on a
#    silent first host cost 60 s to 120 s. apt's defaults (30 s, 3 more tries) would cost 988 s.
#    The setting holds for every source: a source of 1 host (a PPA) gets 1 try, not 4. install.sh's
#    download sets Acquire::Retries and a timeout on apt's command line, which win over this file
#    (apt.conf(5)): in run 44506767788 its 3 and 60 s sent 151 files that failed on the first host back to
#    it, 2 or 3 times. So CI passes the same 0 and 15 s to install.sh (APT_FILE_RETRIES, APT_FILE_TIMEOUT)
#    whenever this script runs.
# security.ubuntu.com, a PPA, a third party's source, Ubuntu's own archive named alone and comments stay.
#
# The files read: sources.list, sources.list.d/*.list, sources.list.d/*.sources, and apt-mirrors.txt,
# the mirror list GitHub's ubuntu-24.04 images name as mirror+file:/etc/apt/apt-mirrors.txt
# (actions/runner-images, images/ubuntu/scripts/build/configure-apt-sources.sh). A source that names
# another mirror list, or no source file at all, or hosts of different paths, is a layout this script
# does not know: it says so and changes nothing. It writes after every new text is made, prints 1 line
# per file it changed, 1 per host it probed and the order it chose, and a second run on the same
# measures changes nothing. Without a mirror list in use, it writes nothing.
#
# apt's behaviour this relies on: apt-transport-mirror(1) ("Fallback order for mirrors": the lowest
# priority first; a file that fails on 1 mirror is asked of the next), and apt 2.8.3's
# apt-pkg/acquire-worker.cc (HandleFailure: Acquire::Retries more tries on the same mirror first).
#
# The probe is the function `probe`; APT_ARCHIVE_PROBE names a stand-in for curl that the tests set
# (sudo drops it on CI, where the step passes only APT_ARCHIVE_CI).
#
# It refuses this machine's own /etc/apt unless APT_ARCHIVE_CI=1 (CI's workflows set it): a person's
# computer keeps the mirror its owner chose. Exit 0 when it ran, 2 when it refused or found no folder.
set -euo pipefail
export LC_ALL=C

say() { printf '[apt-archive] %s\n' "$*"; }
stop() { printf '[apt-archive] %s\n' "$*" >&2; exit 2; }

slow=0
named=()
if [[ "${1:-}" == --slow ]]; then
  slow=1
  shift
  named=("$@")
  set --
fi
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
CONF="$dir/apt.conf.d/80apt-archive-ci"
# The probe: PROBE_BYTES of the index from each host, PROBE_SECONDS for each (curl's own bound), and
# `timeout` ends a probe at PROBE_BOUND s, its kill 1 s later.
PROBE_BYTES=1048576
PROBE_SECONDS=3
PROBE_BOUND=4
# apt's http and https methods: a host silent for TIMEOUT s fails the file; RETRIES more tries on the
# same host, then the next host of the list. apt's defaults are 30 s (methods/basehttp.cc) and 3. The
# mirror list is the retry: 0 sends the file to the next host at once
# (tests/test_ci_apt_archive.py, test_a_silent_first_host_costs_at_most_the_updates_bound).
TIMEOUT=15
RETRIES=0
# A host of the archive's own name with at least 1 label in front: archive.ubuntu.com alone, and
# security.ubuntu.com, do not match. A URI ends at a blank or at the end of the line, so
# my.archive.ubuntu.com.cn matches neither.
URI='https?://([A-Za-z0-9-]+\.)+(archive|ports)\.ubuntu\.com(:[0-9]+)?(/[^[:space:]]*)?([[:space:]]|$)'
EDIT="/^[[:space:]]*#/!s#https?://([A-Za-z0-9-]+\\.)+(archive|ports)\\.ubuntu\\.com(:[0-9]+)?(/[^[:space:]]*)?([[:space:]]|\$)#${KNOWN}\\5#g"

files=()
for f in "$dir/sources.list" "$dir"/sources.list.d/*.list "$dir"/sources.list.d/*.sources; do
  if [[ -f "$f" ]]; then files+=("$f"); fi
done
if [[ "${#files[@]}" -eq 0 && ! -f "$LIST" ]]; then
  say "no apt source file in $dir: a layout this script does not know; changed nothing"
  exit 0
fi

# Every mirror list a source names must be the 1 the images write, and it must be there.
for f in "${files[@]}"; do
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

# A URI as the list holds it: with a / at its end.
slash() { if [[ "$1" == */ ]]; then printf '%s' "$1"; else printf '%s/' "$1"; fi; }
# scheme://host[:port] of a URI, its host, its path.
site() { local r="${1#*://}"; printf '%s://%s' "${1%%://*}" "${r%%/*}"; }
host() { local r="${1#*://}"; r="${r%%/*}"; printf '%s' "${r%%:*}"; }
path() { local r="${1#*://}"; if [[ "$r" == */* ]]; then printf '/%s' "${r#*/}"; else printf '/'; fi; }
# Ubuntu's own host for a regional one: us-east-2.ec2.archive.ubuntu.com -> archive.ubuntu.com.
own() { local h; h="$(host "$1")"; printf '%s' "${1/"$h"/"${h#"${h%.*.ubuntu.com}".}"}"; }

# Writes the list $1 with each URI's line at the priority new[<its index in uris>], into $2: a line's
# priority tag is replaced, or 1 is added after a tab (apt ends the URI at the first tab).
reprioritize() {
  local line u i p
  : > "$2"
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" =~ ^[[:space:]]*(#|$) ]]; then printf '%s\n' "$line" >> "$2"; continue; fi
    u="${line%%$'\t'*}"
    for i in "${!uris[@]}"; do [[ "${uris[$i]}" == "$u" ]] && p="${new[$i]}"; done
    if [[ "$line" =~ (^|[[:space:]])priority:[0-9]+ ]]; then
      line="$(sed -E "s/(^|[[:space:]])priority:[0-9]+/\\1priority:$p/" <<< "$line")"
    elif [[ "$line" == *[[:space:]]* ]]; then
      line+=" priority:$p"
    else
      line+=$'\t'"priority:$p"
    fi
    printf '%s\n' "$line" >> "$2"
  done < "$1"
}

# The hosts of a list, each URI once, in list order, with its priority (none: last).
read_list() {
  local line u x seen p
  uris=()
  prios=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    u="${line%%$'\t'*}"
    seen=0
    for x in "${uris[@]}"; do [[ "$x" == "$u" ]] && seen=1; done
    ((seen)) && continue
    p="$(grep -oE '(^|[[:space:]])priority:[0-9]+' <<< "$line" | head -1 | sed 's/.*://' || true)"
    uris+=("$u")
    prios+=("${p:-999999}")
  done < "$1"
}

# After a download pass too slow to finish (install.sh's APT_SLOW_PASS_COMMAND): the first host named
# that the list holds goes last.
if ((slow)); then
  if [[ ! -f "$LIST" ]]; then
    say "$LIST is absent: no mirror list to reorder after a slow pass; changed nothing"
    exit 0
  fi
  read_list "$LIST"
  late=""
  for h in "${named[@]}"; do
    for u in "${uris[@]}"; do
      if [[ "$(host "$u")" == "$h" ]]; then late="$h"; fi
    done
    if [[ -n "$late" ]]; then break; fi
  done
  if [[ -z "$late" ]]; then
    shown="${named[*]}"
    say "$LIST holds none of the hosts of the slow pass (${shown:-none named}); changed nothing"
    exit 0
  fi
  # Order: the others by priority, then line; the slow host's lines after them.
  order=()
  while read -r _ _ i; do order+=("$i"); done < <(
    for i in "${!uris[@]}"; do
      k=0
      if [[ "$(host "${uris[$i]}")" == "$late" ]]; then k=1; fi
      printf '%s %s %s\n' "$k" "${prios[$i]}" "$i"
    done | sort -k1,1n -k2,2n -k3,3n
  )
  new=()
  named_order=()
  for k in "${!order[@]}"; do
    new[${order[$k]}]=$((k + 1))
    named_order+=("${uris[${order[$k]}]}")
  done
  reprioritize "$LIST" "$work/slow"
  cmp -s -- "$work/slow" "$LIST" || cp -- "$work/slow" "$LIST"
  joined="$(printf '%s\n' "${named_order[@]}" | paste -sd'\t' - | sed 's/\t/, then /g')"
  say "$LIST: $late was too slow (a download pass too slow to finish, or an update try its bound ended); apt asks $joined"
  exit 0
fi

# 1. The regional mirrors named in a source file, by file.
direct=()
changed=()
notes=()
n=0
for f in "${files[@]}"; do
  n=$((n + 1))
  found="$(grep -v '^[[:space:]]*#' -- "$f" | grep -oE "$URI" | sed -E 's#[[:space:]]+$##' || true)"
  [[ -n "$found" ]] || continue
  for u in $found; do direct+=("$(slash "$u")"); done
  sed -E "$EDIT" -- "$f" > "$work/$n"
  hosts="$(for u in $found; do host "$u"; printf '\n'; done | sort -u | paste -sd, - | sed 's/,/, /g')"
  changed+=("$f")
  notes+=("$work/$n|$hosts -> $KNOWN")
done

# The list's lines: URI, a tab, then its tags. apt ends the URI at the first tab, else at the end of
# the line (apt 2.8.3's methods/mirror.cc): a blank before the first tab would be part of the URI.
entries=()
if [[ -f "$LIST" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    u="${line%%$'\t'*}"
    if [[ "$u" =~ [[:space:]] ]]; then
      say "$LIST: a line has a blank before its first tab ($u), and apt reads all of that as the URI:" \
        "a layout this script does not know; changed nothing"
      exit 0
    fi
    entries+=("$u")
  done < "$LIST"
fi

# A list in use: a source names it, now or after step 1.
in_use=0
if ((${#direct[@]})); then in_use=1; fi
for f in "${files[@]}"; do
  if grep -v '^[[:space:]]*#' -- "$f" | grep -qF -- "$KNOWN"; then in_use=1; fi
done
if ((in_use == 0)); then
  say "no regional or cloud mirror of Ubuntu's archive in $dir; changed nothing"
  exit 0
fi

# 1 list serves 1 path of the archive.
paths="$(for u in "${entries[@]}" "${direct[@]}"; do path "$(slash "$u")"; printf '\n'; done | sort -u | paste -sd, - | sed 's/,/, /g')"
if [[ "$paths" == *,* ]]; then
  say "the hosts of Ubuntu's archive in $dir name different paths ($paths): a layout this script does not know;" \
    "changed nothing"
  exit 0
fi

# 2. The list gains each direct mirror, and Ubuntu's own host beside each regional one.
has_host() { local e; for e in "${entries[@]}" "${added[@]}"; do [[ "$(host "$e")" == "$1" ]] && return 0; done; return 1; }
has_uri() { local e; for e in "${entries[@]}" "${added[@]}"; do [[ "$(slash "$e")" == "$1" ]] && return 0; done; return 1; }
added=()
for u in "${direct[@]}"; do
  has_uri "$u" || added+=("$u")
done
for u in "${entries[@]}" "${direct[@]}"; do
  [[ "$(host "$u")" =~ \.(archive|ports)\.ubuntu\.com$ ]] || continue
  o="$(own "$(slash "$u")")"
  has_host "$(host "$o")" || added+=("$o")
done

# The list as it will be before the ranking: the added hosts after the others, at the next priorities.
next=0
if [[ -f "$LIST" ]]; then
  cp -- "$LIST" "$work/list"
  next="$(grep -oE '(^|[[:space:]])priority:[0-9]+' -- "$LIST" | sed 's/.*://' | sort -n | tail -1 || true)"
else
  : > "$work/list"
fi
next="${next:-0}"
for u in "${added[@]}"; do
  next=$((next + 1))
  printf '%s\tpriority:%s\n' "$u" "$next" >> "$work/list"
done

# The hosts in list order, each once, with the priority the runner gave it (none: last).
uris=()
prios=()
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
  u="${line%%$'\t'*}"
  seen=0
  for x in "${uris[@]}"; do [[ "$x" == "$u" ]] && seen=1; done
  ((seen)) && continue
  p="$(grep -oE '(^|[[:space:]])priority:[0-9]+' <<< "$line" | head -1 | sed 's/.*://' || true)"
  uris+=("$u")
  prios+=("${p:-999999}")
done < "$work/list"

# 3. The probe. The suite: the first with no `-` of a source that names the list, else its first.
suites="$(
  for f in "${files[@]}"; do
    sed -E "$EDIT" -- "$f" | awk -v k="$KNOWN" '
      /^[[:space:]]*#/ { next }
      $1 == "deb" || $1 == "deb-src" {
        i = 2
        if ($i ~ /^\[/) { while (i <= NF && $i !~ /\]$/) i++; i++ }
        if ($i == k) print $(i + 1)
        next
      }
      /^[[:space:]]*$/ { if (u) print s; u = 0; s = ""; next }
      $1 == "URIs:" { for (j = 2; j <= NF; j++) if ($j == k) u = 1 }
      $1 == "Suites:" { s = ""; for (j = 2; j <= NF; j++) s = s (j > 2 ? " " : "") $j }
      END { if (u) print s }'
  done | tr ' ' '\n' | sed '/^$/d'
)"
suite="$(grep -v -- - <<< "$suites" | head -1 || true)"
suite="${suite:-$(head -1 <<< "$suites")}"
case "$(uname -m)" in
  x86_64) arch=amd64 ;;
  aarch64 | arm64) arch=arm64 ;;
  *) arch="" ;;
esac

# Prints "<HTTP code> <bytes> <seconds>" for the first PROBE_BYTES of $1.
probe() {
  if [[ -n "${APT_ARCHIVE_PROBE:-}" ]]; then
    timeout -k 1 "$PROBE_BOUND" "$APT_ARCHIVE_PROBE" "$1"
  else
    timeout -k 1 "$PROBE_BOUND" curl -sS -o /dev/null -r "0-$((PROBE_BYTES - 1))" --connect-timeout "$PROBE_SECONDS" \
      --max-time "$PROBE_SECONDS" -w '%{http_code} %{size_download} %{time_total}' -- "$1"
  fi
}

if ((${#uris[@]} == 0)); then
  say "$LIST names no host: a layout this script does not know; changed nothing"
  exit 0
fi

# The probe's lines wait for the writes' lines: the log reads in the order the step decided.
heard=()
ranked=()
if [[ -z "$suite" || -z "$arch" ]]; then
  heard+=("no probe: no suite names the list, or $(uname -m) is an architecture this script does not know")
else
  index="dists/$suite/main/binary-$arch/Packages.gz"
  pids=()
  for i in "${!uris[@]}"; do
    probe "$(slash "${uris[$i]}")$index" > "$work/probe.$i" 2> /dev/null &
    pids+=("$!")
  done
  answers=()
  for i in "${!uris[@]}"; do
    rc=0
    wait "${pids[$i]}" || rc=$?
    read -r code got secs rest < "$work/probe.$i" || true
    if ((rc == 124 || rc == 137)); then
      heard+=("probe ${uris[$i]}: no answer (nothing within $PROBE_BOUND s); it goes last")
    elif [[ ! "${code:-}" =~ ^[0-9]{3}$ || ! "${got:-}" =~ ^[0-9]+$ || ! "${secs:-}" =~ ^[0-9]+(\.[0-9]+)?$ || -n "${rest:-}" ]]; then
      heard+=("probe ${uris[$i]}: no answer (unreadable: $(head -c 80 "$work/probe.$i")); it goes last")
    elif [[ "$code" != 200 && "$code" != 206 ]] || ((got == 0)); then
      heard+=("probe ${uris[$i]}: no answer (HTTP $code, $got bytes); it goes last")
    else
      rate="$(awk -v b="$got" -v s="$secs" 'BEGIN { if (s > 0) printf "%d", b / s; else printf "%d", b }')"
      heard+=("probe ${uris[$i]}: $got bytes in $secs s, $rate bytes/s")
      answers+=("$rate $i")
    fi
    code="" got="" secs="" rest=""
  done
  if ((${#answers[@]})); then
    while read -r _ i; do ranked+=("$i"); done < <(printf '%s\n' "${answers[@]}" | sort -k1,1nr -k2,2n)
  fi
fi

# The runner's order: by its priority, then by line.
runners=()
while read -r _ i; do runners+=("$i"); done < <(for i in "${!uris[@]}"; do printf '%s %s\n' "${prios[$i]}" "$i"; done | sort -k1,1n -k2,2n)

order=()
for i in "${ranked[@]}" "${runners[@]}"; do
  in=0
  for x in "${order[@]}"; do [[ "$x" == "$i" ]] && in=1; done
  ((in)) || order+=("$i")
done
named=()
for i in "${order[@]}"; do named+=("${uris[$i]}"); done
joined="$(printf '%s\n' "${named[@]}" | paste -sd'\t' - | sed 's/\t/, then /g')"

# With no answer apt keeps the runner's priorities, and takes hosts of 1 priority, or of none, in random
# order (apt-transport-mirror(1), "Fallback order for mirrors"; methods/mirror.cc sorts by a random seed
# after the priority). So the line names an order only between priorities.
groups=()
last=""
for i in "${runners[@]}"; do
  if ((${#groups[@]})) && [[ "${prios[$i]}" == "$last" ]]; then
    groups[-1]+=$'\t'"${uris[$i]}"
  else
    groups+=("${uris[$i]}")
  fi
  last="${prios[$i]}"
done
random=0
for k in "${!groups[@]}"; do
  g="${groups[$k]}"
  if [[ "$g" == *$'\t'* ]]; then
    random=1
    front="${g%$'\t'*}"
    groups[k]="${front//$'\t'/, } and ${g##*$'\t'} in random order"
  fi
done
kept="$(printf '%s\n' "${groups[@]}" | paste -sd'\t' - | sed 's/\t/, then /g')"

# The new priorities: 1 for the first of the order. With no answer, the runner's priorities stay.
if ((${#ranked[@]})); then
  new=()
  for k in "${!order[@]}"; do new[${order[$k]}]=$((k + 1)); done
  : > "$work/ranked"
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" =~ ^[[:space:]]*(#|$) ]]; then printf '%s\n' "$line" >> "$work/ranked"; continue; fi
    u="${line%%$'\t'*}"
    for i in "${!uris[@]}"; do [[ "${uris[$i]}" == "$u" ]] && p="${new[$i]}"; done
    if [[ "$line" =~ (^|[[:space:]])priority:[0-9]+ ]]; then
      line="$(sed -E "s/(^|[[:space:]])priority:[0-9]+/\\1priority:$p/" <<< "$line")"
    elif [[ "$line" == *[[:space:]]* ]]; then
      line+=" priority:$p"
    else
      line+=$'\t'"priority:$p"
    fi
    printf '%s\n' "$line" >> "$work/ranked"
  done < "$work/list"
  mv -- "$work/ranked" "$work/list"
fi

cat > "$work/conf" << EOF
// Written by tools/ci/apt_archive.sh, on CI's install path only (APT_ARCHIVE_CI=1).
// A file whose host sends nothing for $TIMEOUT s gets $RETRIES more tries there; apt's mirror method
// asks the next host of the mirror list for it. apt's own defaults are 30 s and 3 more tries.
// It holds for every source: a source of 1 host gets 1 try.
Acquire::http::Timeout "$TIMEOUT";
Acquire::https::Timeout "$TIMEOUT";
Acquire::Retries "$RETRIES";
EOF

# The writes, after every new text is made. cp onto a file keeps its owner and mode; a new file is 0644.
for i in "${!changed[@]}"; do
  cp -- "${notes[$i]%%|*}" "${changed[$i]}"
  say "${changed[$i]}: ${notes[$i]#*|}"
done
if [[ ! -f "$LIST" ]]; then
  install -m 0644 -- "$work/list" "$LIST"
elif ! cmp -s -- "$work/list" "$LIST"; then
  cp -- "$work/list" "$LIST"
fi
if ((${#added[@]})); then
  say "$LIST: added $(printf '%s\n' "${added[@]}" | paste -sd'\t' - | sed 's/\t/, /g')"
fi
for h in "${heard[@]}"; do say "$h"; done
if ((${#ranked[@]})); then
  say "$LIST: apt asks $joined: the fastest in a 1 MiB sample first"
elif ((random)); then
  say "$LIST: no host answered the probe; apt asks by the runner's priorities: $kept"
else
  say "$LIST: no host answered the probe; apt asks in the runner's order: $kept"
fi
mkdir -p -- "$dir/apt.conf.d"
cmp -s -- "$work/conf" "$CONF" || install -m 0644 -- "$work/conf" "$CONF"
say "$CONF: a file whose host is silent for $TIMEOUT s gets $RETRIES more tries there, then apt asks the next host" \
  "(Acquire::http::Timeout $TIMEOUT, Acquire::https::Timeout $TIMEOUT, Acquire::Retries $RETRIES)"
