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
