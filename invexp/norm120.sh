#!/usr/bin/env bash
# Usage: ./norm120.sh <dataset> [fps]
# Converts every .mov/.mp4 in <dataset> to constant-frame-rate lossless
# FFV1 AVI in <dataset>/normalized/, then checks the frame counts match.
#
# <dataset> is resolved against INVEXP_DATA_DIR unless it is absolute.
# Example: ./norm120.sh walkTest 120

set -uo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$here/data_root.sh"

dir="${1:-}"
rate="${2:-120}"

if [[ -z "$dir" ]]; then
  echo "usage: $0 <dataset> [fps]" >&2
  echo "datasets: calibration, walkTest" >&2
  exit 2
fi

if [[ "$dir" != /* ]]; then
  dir="$INVEXP_DATA_DIR/$dir"
fi

if [[ ! -d "$dir" ]]; then
  echo "error: dataset directory not found: $dir" >&2
  echo "set INVEXP_DATA_DIR or pass an absolute path" >&2
  exit 1
fi

for tool in ffmpeg ffprobe; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "error: $tool not found in PATH" >&2
    exit 1
  fi
done

out="$dir/normalized"
mkdir -p "$out"
shopt -s nullglob nocaseglob

count() {
  ffprobe -v error -select_streams v:0 -count_frames \
    -show_entries stream=nb_read_frames -of csv=p=0 "$1"
}

for src in "$dir"/*.mov "$dir"/*.mp4; do
  base=$(basename "${src%.*}")
  dst="$out/${base}_${rate}fps_ffv1.avi"

  if [[ -f "$dst" ]]; then
    echo "skip   $base (already converted)"
    continue
  fi

  echo "==> $base"
  if ! ffmpeg -hide_banner -loglevel warning -stats -nostdin -y -i "$src" \
      -map 0:v:0 -an \
      -vf "setpts=N/($rate*TB)" -r "$rate" \
      -c:v ffv1 -level 3 -coder 1 -context 1 -g 1 -slices 16 -slicecrc 1 \
      "$dst"; then
    echo "FAILED $base"
    rm -f "$dst"
    continue
  fi

  n_in=$(count "$src"); n_out=$(count "$dst")
  if [[ "$n_in" == "$n_out" ]]; then
    echo "OK     $base  ($n_out frames)"
  else
    echo "MISMATCH $base  src=$n_in out=$n_out  <-- check this one"
  fi
done
