#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

missing=()
for tool in python3 node npm gpg curl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        missing+=("$tool")
    fi
done
if (( ${#missing[@]} > 0 )); then
    printf 'Missing tools: %s\n' "${missing[*]}" >&2
    printf 'See “Check the Mac tools” in README.md for the individual installers or Homebrew.\n' >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' ||
   ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 22 ? 1 : 0)'; then
    printf 'Use Python 3.10 or newer and Node.js 22 or newer.\n' >&2
    exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
    printf 'Creating a local Python environment…\n'
    python3 -m venv .venv
fi

python_signature=$(shasum -a 256 requirements.txt)
if [[ ! -f .venv/requirements.sha256 || $(<.venv/requirements.sha256) != "$python_signature" ]]; then
    printf 'Installing Python libraries…\n'
    .venv/bin/python -m pip install -r requirements.txt
    printf '%s\n' "$python_signature" > .venv/requirements.sha256
fi

node_signature=$(shasum -a 256 package.json package-lock.json)
if [[ ! -f node_modules/.robosats-dependencies.sha256 ||
      $(<node_modules/.robosats-dependencies.sha256) != "$node_signature" ]]; then
    printf 'Installing chat libraries…\n'
    npm ci --ignore-scripts --no-audit --no-fund
    printf '%s\n' "$node_signature" > node_modules/.robosats-dependencies.sha256
fi

exec .venv/bin/python robosats_monitor.py "$@"
