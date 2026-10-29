#!/usr/bin/env bash
# Copy the invoicing fixture source to <dest>, initialise it as
# a fresh git repository on branch "main", commit it, and print
# the commit SHA as the last line of output.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <dest>" >&2
  exit 2
fi

dest="$1"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src_dir="$(cd "${script_dir}/../fixture-repo-src" && pwd)"

mkdir -p "${dest}"

# Copy the fixture, excluding caches and any VCS metadata.
if command -v rsync >/dev/null 2>&1; then
  rsync -a --exclude '__pycache__' --exclude '.pytest_cache' --exclude '.git' "${src_dir}/" "${dest}/"
else
  (cd "${src_dir}" && tar --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.git' -cf - .) | (cd "${dest}" && tar -xf -)
fi

git -C "${dest}" init --initial-branch=main >/dev/null
git -C "${dest}" add -A
git -C "${dest}" -c user.name="TokenPilot Demo" -c user.email="demo@tokenpilot.invalid" commit -m "Initial fixture commit" >/dev/null

git -C "${dest}" rev-parse HEAD
