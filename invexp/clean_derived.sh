#!/usr/bin/env bash
# List generated FFV1 files. Pass --yes to delete them.
# Source camera media is never touched.

set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$here/data_root.sh"

if [[ ! -d "$INVEXP_DATA_DIR" ]]; then
  echo "error: data root not found: $INVEXP_DATA_DIR" >&2
  exit 1
fi

files=$(find "$INVEXP_DATA_DIR" -type f -name '*_ffv1.avi' -print | LC_ALL=C sort)
if [[ -z "$files" ]]; then
  echo "no generated FFV1 files under $INVEXP_DATA_DIR"
  exit 0
fi

printf '%s\n' "$files"

if [[ "${1:-}" != "--yes" ]]; then
  echo
  echo "dry run; re-run with --yes to delete the files above"
  exit 0
fi

while IFS= read -r file; do
  rm -- "$file"
  echo "deleted $file"
done <<< "$files"
