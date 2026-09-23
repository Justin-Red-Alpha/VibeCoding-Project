#!/usr/bin/env bash
# drift-check — every `path:symbol` claimed in docs/*/IMPLEMENTATION.md must resolve.
#
# The model says where code should live; this proves it still does. A dead row is drift.
# Exits non-zero when anything is dead, so it drops straight into CI.
#
#   drift-check.sh [repo]            human-readable report
#   drift-check.sh [repo] --json     {"dead":N,"total":N,"rows":[...]}
#   drift-check.sh --selftest        build a fixture, assert both exit codes
#
# Ceiling (deliberate, see README): symbols are matched by substring grep, so a
# renamed symbol that survives as a substring elsewhere in the file still passes,
# and refs written as a bare filename (`order.py:Order.total`, no directory) are
# skipped to avoid matching prose. Upgrade path when it matters: resolve through
# `semble search "<symbol>" <repo>` or an LSP — not a stricter regex.
set -uo pipefail

REPO="."
JSON=0
for a in "$@"; do
  case "$a" in
    --json)     JSON=1 ;;
    --selftest) SELFTEST=1 ;;
    -h|--help)  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)          REPO="$a" ;;
  esac
done

# ---------------------------------------------------------------- self-test
if [ "${SELFTEST:-0}" = 1 ]; then
  tmp=$(mktemp -d) || exit 2
  trap 'rm -rf "$tmp"' EXIT
  mkdir -p "$tmp/src" "$tmp/docs/widget"
  printf 'class Widget:\n    def render(self):\n        pass\n' > "$tmp/src/widget.py"
  cat > "$tmp/docs/widget/IMPLEMENTATION.md" <<'FIX'
| Object | Realised at |
| --- | --- |
| `Widget` | `src/widget.py:Widget` |
| `render` | `src/widget.py:Widget::render` |
| `ghost`  | `src/gone.py:Ghost` |
FIX
  ( cd "$tmp" && git init -q . && git add -A && git -c user.email=t@t -c user.name=t commit -qm f )

  out=$("$0" "$tmp" 2>&1); rc=$?
  [ "$rc" -ne 0 ]                        || { echo "FAIL: stale row did not exit non-zero"; exit 1; }
  case "$out" in *"DEAD-PATH"*) ;; *) echo "FAIL: dead path not reported: $out"; exit 1 ;; esac
  case "$out" in *"3 refs"*)    ;; *) echo "FAIL: expected 3 refs scanned: $out"; exit 1 ;; esac

  sed -i.bak '/gone.py/d' "$tmp/docs/widget/IMPLEMENTATION.md" && rm -f "$tmp/docs/widget/IMPLEMENTATION.md.bak"
  out=$("$0" "$tmp" 2>&1); rc=$?
  [ "$rc" -eq 0 ]                        || { echo "FAIL: clean tree did not exit zero: $out"; exit 1; }

  "$0" "$tmp" --json | grep -q '"dead": *0' || { echo "FAIL: --json shape wrong"; exit 1; }
  echo "selftest OK"
  exit 0
fi

# ---------------------------------------------------------------- checks
cd "$REPO" 2>/dev/null || { echo "drift-check: no such directory: $REPO" >&2; exit 2; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "drift-check: not a git repo (needs git ls-files to resolve paths)" >&2; exit 2; }
[ -d docs ] || { [ "$JSON" = 1 ] && echo '{"dead": 0, "total": 0, "rows": []}' \
                                 || echo "no docs/ tree here — nothing to check"; exit 0; }

idx=$(git ls-files); dead=0; total=0; rows=""

while IFS= read -r doc; do
  while IFS= read -r ref; do
    path="${ref%%:*}"; rest="${ref#*:}"; sym="${rest##*:}"   # path:Sym and path:Sym::method
    case "$path" in */*) ;; *) continue ;; esac              # bare filenames: too prose-like
    total=$((total+1)); esc=${path//./\\.}
    hits=$(printf '%s\n' "$idx" | grep -E "(^|/)${esc}$")    # suffix match: docs may be service-relative
    if [ -z "$hits" ]; then
      [ "$JSON" = 1 ] && rows="$rows{\"kind\":\"dead-path\",\"doc\":\"$doc\",\"ref\":\"$path\"}," \
                      || echo "DEAD-PATH   $doc -> $path"
      dead=$((dead+1)); continue
    fi
    { [ -z "$sym" ] || [ "$sym" = "$path" ]; } && continue
    found=0
    while IFS= read -r h; do grep -qF -- "$sym" "$h" 2>/dev/null && { found=1; break; }; done <<< "$hits"
    if [ "$found" -eq 0 ]; then
      [ "$JSON" = 1 ] && rows="$rows{\"kind\":\"dead-symbol\",\"doc\":\"$doc\",\"ref\":\"$path:$sym\"}," \
                      || echo "DEAD-SYMBOL $doc -> $path:$sym"
      dead=$((dead+1))
    fi
  done < <(grep -o '`[^`]*`' "$doc" | tr -d '`' \
           | grep -E '^[A-Za-z0-9_./-]+\.[A-Za-z0-9]+::?[A-Za-z0-9_:]+$')
done < <(find docs -name IMPLEMENTATION.md)

if [ "$JSON" = 1 ]; then
  printf '{"dead": %d, "total": %d, "rows": [%s]}\n' "$dead" "$total" "${rows%,}"
else
  echo "--- $dead dead / $total refs"
fi
[ "$dead" -eq 0 ]
