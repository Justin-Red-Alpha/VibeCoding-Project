#!/usr/bin/env bash
# preflight — report which supercharge dependencies are present, and their versions.
#
# Informational only. NEVER exits non-zero: a missing tool degrades a mode, it does
# not end a session. Run at the top of `start` so version drift surfaces early.
missing=0

# Installers drop binaries in per-tool dirs and export them from ~/.zshrc, which only
# INTERACTIVE shells read — so an agent's shell sees a tool as missing when it is not.
# Widen the search so the report is truthful, then say which dirs need prepending.
offpath=""
for d in "$HOME/.bun/bin" "$HOME/.local/bin"; do
  [ -d "$d" ] || continue
  case ":$PATH:" in *":$d:"*) ;; *) PATH="$d:$PATH"; offpath="$offpath $d" ;; esac
done
export PATH

have() { command -v "$1" >/dev/null 2>&1; }
ver()  { "$@" 2>/dev/null | head -1; }

if have graphify; then echo "graphify  $(ver graphify --version || echo present)"
else echo "graphify  MISSING → uv tool install graphifyy"; missing=1; fi

if have openspec; then echo "openspec  $(ver openspec --version)"
else echo "openspec  MISSING → npm install -g @fission-ai/openspec@latest"; missing=1; fi

if   have semble; then echo "semble    $(ver semble --version)"
elif have uvx;    then echo "semble    via uvx (no local install)"
else echo "semble    MISSING → uv tool install 'semble[mcp]==0.5.5'"; missing=1; fi

if have gbrain; then
  # Installed is not the same as usable: `gbrain init` is interactive and no installer
  # can run it, so the binary exists long before a brain does. `doctor` exits 0 either
  # way, so match its output rather than its status.
  if gbrain doctor 2>&1 | grep -qi "no brain configured"; then
    echo "gbrain    $(ver gbrain --version) — INSTALLED BUT NO BRAIN → run: gbrain init (interactive)"
    echo "          until then, skip the capture step at the end of 'end'"
  else
    echo "gbrain    $(ver gbrain --version)"
  fi
else echo "gbrain    MISSING → bun install -g github:garrytan/gbrain   (NOT npm — that is a different package)"; missing=1; fi

have git || { echo "git       MISSING → required by drift-check"; missing=1; }

[ -f openspec/config.yaml ]    || echo "note: no openspec/ here    → run: openspec init  (then paste the rules block, see references/openspec.md)"
[ -d docs ]                    || echo "note: no docs/ tree here   → ask supercharge to scaffold it"
[ -f graphify-out/graph.json ] || echo "note: no graph here        → run: graphify ."

[ -n "$offpath" ] && echo "note: found via a dir not on this shell's \$PATH —$offpath
      prepend it before running these tools, or they will look missing"

[ "$missing" -eq 0 ] && echo "preflight OK"
exit 0   # informational only — never block a session
