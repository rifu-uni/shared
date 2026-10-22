# ESP32-S3 inertial node — first bring-up

Bench bring-up for **one BMI160**, both directly on the ESP32-S3 I2C bus and
behind **one TCA9548A** multiplexer on channel 0. The microSD card is not part
of this test.

Everything here is self-contained; no third-party Arduino libraries are needed.

## Contents

| Path | Purpose |
|---|---|
| `firmware/esp32_bmi160_bringup/` | Arduino sketch + minimal BMI160 and TCA9548A drivers |
| `scripts/flash.sh` | Serial monitor by default; `--flash` compiles and uploads |
| `scripts/monitor.sh` | Open the 115200 baud monitor |
| `schematic/direct_bmi160.pdf` | Printable direct wiring sheet |
| `schematic/mux_tca9548a_bmi160_ch0.pdf` | Printable mux + channel 0 sheet |
| `schematic/WIRING.md` | Port-by-port tables, physical header map, checklist, troubleshooting |
| `schematic/netlist.csv` | Machine-readable netlist for both options |
| `schematic/generate_schematic.py` | Single source of truth for the drawings |

## Wiring in one sentence

**SDA = GPIO8 (J1 pin 12), SCL = GPIO9 (J1 pin 15), 3.3 V, common ground.**
On the GY-BMI160: `VIN` to 3.3 V (leave the `3V3` pin open), `CS` HIGH for I2C,
`SA0` LOW = `0x68` (HIGH or floating = `0x69`). Leave `SCX`, `SDX`, `OCS`,
`INT1`, `INT2` open. TCA9548A `RESET` must be HIGH, `A0/A1/A2` LOW for `0x70`.

The GY-BMI160 has 3.9 kΩ pull-ups tied to `VIN`; **never feed `VIN` from 5 V**
or the I2C lines will be pulled to 5 V.

See `schematic/WIRING.md` for every individual wire and the continuity checks.

## Build and run

One-time core install:

```bash
arduino-cli core install esp32:esp32
```

Then, from the workspace root:

```bash
./invexp/esp320/scripts/flash.sh --flash
```

`--flash` compiles and uploads, then opens the monitor. Without it the script
only opens the monitor, so an already-flashed board is not rewritten.

Or from this directory:

```bash
./scripts/flash.sh --flash
./scripts/flash.sh              # monitor only
```

The script auto-detects a single `/dev/cu.usbmodem*` port. Override with
`--port /dev/cu.usbmodem...` when needed. Add `--no-monitor` to stop after an
upload. On the native USB port (VID `0x303A`), `--flash` automatically adds
`CDCOnBoot=cdc` so `Serial` goes to USB; on the CH343 UART port it keeps UART0.
Use `--no-cdc` to keep UART0 on native USB.

## Serial commands

| Key | Action |
|---|---|
| `s` | Scan the upstream I2C bus |
| `m` | Scan mux channels 0–7 |
| `d` | Read the direct BMI160 |
| `0` | Read the BMI160 on mux channel 0 |
| `r` | Stream accel + gyro at 10 Hz |
| `x` | Stop streaming |
| `i` | Configuration and sensor health |
| `?` | Help |

## Regenerating the drawings

Dependencies are managed by pixi at the workspace root. From
`/Users/rifusaki/localRepos/uni`:

```bash
pixi install
pixi run schematic
```

The generator writes SVG, PNG and PDF for both sheets plus `netlist.csv`, and
fails if the drawing nets and the netlist disagree.
