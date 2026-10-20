#!/usr/bin/env bash
# Usage: ./dt_csv.sh video1.MOV [video2.MOV ...]
# Writes <video>_dt.csv next to each input unless DT_OUT_DIR is set.
# Relative input paths are resolved against INVEXP_DATA_DIR when they do not
# exist in the current directory.

set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$here/../data_root.sh"

if [[ $# -eq 0 ]]; then
  echo "usage: $0 video1.MOV [video2.MOV ...]" >&2
  exit 2
fi

out_dir="${DT_OUT_DIR:-}"

for src in "$@"; do
  if [[ ! -e "$src" && "$src" != /* ]]; then
    src="$INVEXP_DATA_DIR/$src"
  fi

  if [[ ! -f "$src" ]]; then
    echo "error: input not found: $src" >&2
    exit 1
  fi

  base=$(basename "${src%.*}")
  out="${out_dir:-$(dirname "$src")}/${base}_dt.csv"
  mkdir -p "$(dirname "$out")"

  tmp=$(mktemp "${out}.XXXXXX")
  if ! ffprobe -v error -select_streams v:0 -show_entries frame=pts_time -of csv=p=0 "$src" \
      | tr -d ',' | sort -g \
      | awk 'BEGIN { print "frame,pts_s,dt_s,dt_ms" }
             NR==1 { printf "0,%.6f,,\n", $1 }
             NR>1  { printf "%d,%.6f,%.6f,%.3f\n", NR-1, $1, $1-p, ($1-p)*1000 }
             { p=$1 }' > "$tmp"; then
    rm -f "$tmp"
    echo "FAILED $src" >&2
    exit 1
  fi

  mv "$tmp" "$out"
  echo "wrote $out"
done
