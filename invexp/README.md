## Data

Heavy InvExp media lives outside this Git repository. Default root:

```text
/Users/rifusaki/Documents/University/XII/InvExp/data
```

Override it with `INVEXP_DATA_DIR`:

```bash
export INVEXP_DATA_DIR=/path/to/InvExp/data
```

Layout:

```text
$INVEXP_DATA_DIR/
├── calibration/
│   ├── *.MOV
│   └── normalized/*_ffv1.avi
└── walkTest/
    ├── *.MOV
    └── normalized/*_ffv1.avi
```

Only source `.MOV` files and generated FFV1 AVIs live there. Small analysis
outputs (`.csv`, `.trk`, notebooks) stay in Git.

## Commands

```bash
pixi run norm-walk          # convert walk clips to 120 fps FFV1
pixi run normalize -- calibration 60  # other datasets need explicit fps
pixi run dt-walk            # regenerate frame-timing CSVs
pixi run manifest           # refresh manifests/SHA256SUMS
pixi run clean-derived      # list generated FFV1 files (dry run)
pixi run clean-derived -- --yes  # delete generated FFV1 files
```

Source media is never deleted by `clean-derived`. Calibration clips have mixed
native frame rates (30/60/120/240), so they are not normalized by a default task.

## Pose pipeline

Inference-only MediaPipe pipeline. It extracts pose landmarks, sagittal joint
angles and contact events from the walk clips. It does **not** estimate impact
acceleration from video; the BMI160/FSR channels remain the impact reference.

The main pixi environment is Python 3.14. MediaPipe has no conda-forge package
for macOS ARM, so the pose stack lives in a dedicated pixi environment called
`pose` (Python 3.12) instead of mixing native ML libraries into the notebook
environment. Pixi still owns every package.

```bash
pixi install -e pose
```

Run from the repository root:

```bash
pixi run -e pose pose probe "$INVEXP_DATA_DIR/walkTest/001.MOV"
pixi run -e pose pose run "$INVEXP_DATA_DIR/walkTest/001.MOV" \
  --video-id 001 --output-dir invexp/walkTest/pose
pixi run -e pose pose batch --output-dir invexp/walkTest/pose
pixi run -e pose pose-test
pixi run -e pose pose-overlays
```

Models are downloaded on first use to `invexp/pose/models/` and verified against
pinned SHA256 hashes. They are gitignored.

Outputs:

```text
$INVEXP_DATA_DIR/derived/pose/<id>_landmarks.csv.gz   # large, outside Git
invexp/walkTest/pose/<id>_kinematics.csv.gz          # angles + pixel coordinates
invexp/walkTest/pose/<id>_events.csv                 # contacts, toe-off, cadence
invexp/walkTest/pose/<id>_run.json                   # QA metadata
invexp/walkTest/pose/<id>_report.md                  # human summary
invexp/walkTest/pose/<id>_overlay.mp4                # optional visual QA
invexp/walkTest/pose/events_all.csv                  # batch concatenation
invexp/walkTest/pose/summary.csv                     # batch QA table
```

Visual QA overlays:

```bash
# Re-render every run in invexp/walkTest/pose (force overwrite).
pixi run -e pose pose-overlays

# One clip. Uses the run metadata and landmark table from the output dir.
pixi run -e pose pose overlay \
  --video-id 001 --output-dir invexp/walkTest/pose

# Lower-level batch command; skips existing files unless --force is added.
pixi run -e pose pose overlay-batch \
  --output-dir invexp/walkTest/pose
```

The default export is the longest continuous pose detections, plus one second
of padding, at 1280×720 and source frame rate. Contact and toe-off frames get a
ring and label. Use `--full` for the whole source clip, `--start/--end` for an
exact window, `--max-width` to change resolution, and `--force` to overwrite.
Overlays are QA artifacts, not pipeline inputs; `--full` on a 120 fps clip is
large and slow.

Validation against the existing Tracker annotation:

```bash
pixi run -e pose pose validate \
  --kinematics invexp/walkTest/pose/001_kinematics.csv.gz \
  --events invexp/walkTest/pose/001_events.csv \
  --trk invexp/walkTest/001_120fps_ffv1.trk \
  --manual-csv invexp/walkTest/normalized/001_120fps_ffv1.csv \
  --side left --out invexp/walkTest/pose/001_validation.json
```

The 001 run matches 3/4 manual contacts within 150 ms (bias +67 ms, SD 5 ms).

The manual annotation is compared point by point in
`invexp/walkTest/pose/001_manual_vs_pose.ipynb`. Manual mass B is the ankle, so
the matching pose landmark is `left_ankle` (centered RMSE ~8 px resultant), not
the heel/foot-index midpoint (~29 px). The sacral proxy is the hip midpoint
(centered RMSE ~10 px); its raw offset is marker placement, not model noise.

```bash
pixi run -e default jupyter nbconvert --to notebook --execute --inplace \
  invexp/walkTest/pose/001_manual_vs_pose.ipynb
```

`003` is oblique: use it for event robustness, not sagittal angles.

IMU logs are not present yet. The parser accepts `time_s`/`timestamp_ms` and
`ax_g`/`ax_m_s2`-style columns and detects impact peaks; real comparison stays
blocked until firmware logs exist.
