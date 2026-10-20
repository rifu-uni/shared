# Data manifests

`SHA256SUMS` covers source camera media (`.MOV` / `.mp4`) under
`$INVEXP_DATA_DIR`. Generated FFV1 files are excluded because they can be
rebuilt with `pixi run norm-calibration` or `pixi run norm-walk`.

Regenerate after adding or replacing source footage:

```bash
pixi run manifest
```
