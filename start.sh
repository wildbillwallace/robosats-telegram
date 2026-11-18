#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

node_version_check='process.exit(Number(process.versions.node.split(".")[0]) < 22 ? 1 : 0)'
if ! node -e "$node_version_check" 2>/dev/null; then
    nvm_script="${NVM_DIR:-$HOME/.nvm}/nvm.sh"
    if [[ -s "$nvm_script" ]]; then
        set +u
        if source "$nvm_script" --no-use; then
            nvm use --silent default >/dev/null || true
        fi
        set -u
    fi
fi

missing=()
for tool in python3 node npm gpg curl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        missing+=("$tool")
    fi
done
if (( ${#missing[@]} > 0 )); then
    printf 'Missing tools: %s\n' "${missing[*]}" >&2
    printf 'See “Check the Mac tools” in SETUP-MACOS.md for the individual installers or Homebrew.\n' >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' ||
   ! node -e "$node_version_check"; then
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
