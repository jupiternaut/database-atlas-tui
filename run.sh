#!/usr/bin/env bash
set -euo pipefail
atlas_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "$atlas_dir/.venv/bin/python" ]]; then
  printf 'Missing local environment. Run: uv venv "%s/.venv"\n' "$atlas_dir" >&2
  printf 'Then: uv pip install --python "%s/.venv/bin/python" -r "%s/requirements.txt"\n' "$atlas_dir" "$atlas_dir" >&2
  exit 1
fi
exec env -u PYTHONPATH "$atlas_dir/.venv/bin/python" "$atlas_dir/app.py" "$@"
