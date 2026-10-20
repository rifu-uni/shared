#!/usr/bin/env bash
# Regenerate manifests/SHA256SUMS for source camera media.
# Covers .mov/.mp4 files under INVEXP_DATA_DIR; excludes derived FFV1 files.

set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$here/data_root.sh"

if [[ ! -d "$INVEXP_DATA_DIR" ]]; then
  echo "error: data root not found: $INVEXP_DATA_DIR" >&2
  exit 1
fi

cd "$INVEXP_DATA_DIR"

files=$(find calibration walkTest -type f \( -iname '*.mov' -o -iname '*.mp4' \) -print 2>/dev/null | LC_ALL=C sort)
if [[ -z "$files" ]]; then
  echo "error: no source media found under $INVEXP_DATA_DIR" >&2
  exit 1
fi

mkdir -p "$here/../manifests"
printf '%s\n' "$files" | xargs shasum -a 256 > "$here/../manifests/SHA256SUMS"
echo "wrote $here/../manifests/SHA256SUMS"
