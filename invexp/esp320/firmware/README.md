# ESP32-S3 BMI160 + TCA9548A bring-up

Firmware for the inertial node bring-up. It scans the I2C bus, finds a TCA9548A
multiplexer at `0x70`, scans all eight downstream channels, and reads one BMI160
directly or through mux channel 0.

- Board: ESP32-S3 DevKitC-1 N16R8 (16 MB flash, 8 MB PSRAM)
- Serial: UART0 through the CH343 bridge by default; `flash.sh --flash` auto-enables CDC on the native USB port
- I2C: SDA = GPIO8, SCL = GPIO9, 100 kHz for bring-up
- BMI160: `0x68` with `SA0` low, `0x69` with `SA0` high (R4 pulls it high by default)
- TCA9548A: `0x70` with A0/A1/A2 tied to GND

## Wiring

### A. BMI160 direct to the ESP32-S3

Use this first, before adding the mux. It proves the sensor, address, and wiring.

| GY-BMI160 pin | ESP32-S3 DevKitC-1 | Note |
|---|---|---|
| `VIN` | 3V3 | 3.3 V into the onboard LDO and the four 3.9 kΩ pull-ups; never 5 V |
| `3V3` | — | LDO output; leave open |
| `GND` | GND | Common ground with the ESP32 |
| `SDA` | GPIO8 | I2C data |
| `SCL` | GPIO9 | I2C clock |
| `CS` | 3V3 | **Must be high.** R3 already pulls it high; tie it explicitly. Low/floating selects SPI and the sensor disappears from I2C |
| `SA0` | GND for `0x68` | R4 pulls it high by default → `0x69`. Firmware probes both |
| `INT1`, `INT2`, `SCX`, `SDX`, `OCS` | — | Leave open |
| SDA, SCL pull-ups | Onboard 3.9 kΩ to `VIN` | Do not add more for one sensor |

Do not connect the BMI160 to both the direct bus and a mux channel at the same
time. That puts it on the upstream bus and defeats the mux test. For the same
reason, a direct BMI160 and a mux BMI160 must not share an address: the mux scan
filters upstream addresses, so a colliding downstream device is hidden.

### B. TCA9548A with one BMI160 on channel 0

| TCA9548A | Connects to | Note |
|---|---|---|
| VCC | 3V3 | Do not feed 5 V into the 3.3 V rail |
| GND | GND | Common ground |
| SDA | GPIO8 + pull-up to 3V3 | Upstream I2C bus |
| SCL | GPIO9 + pull-up to 3V3 | Upstream I2C bus |
| RESET | 3V3 (directly or through 10 kOhm) | Floating RESET can reset the mux at random |
| A0, A1, A2 | GND | Address `0x70` |
| SD0 | BMI160 SDA | Channel 0 data |
| SC0 | BMI160 SCL | Channel 0 clock |
| SD1-SD7, SC1-SC7 | Not connected | Reserved for sensors 2-5 |

The BMI160 on channel 0 keeps the same connections as configuration A, except
SDA/SCL go to `SD0`/`SC0` of the mux instead of GPIO8/GPIO9. `CS` still goes to
3V3 and `SA0` still selects `0x68` or `0x69`.

```
ESP32-S3                    TCA9548A                    GY-BMI160 (CH0)
GPIO8  -------------------- SDA
GPIO9  -------------------- SCL
3V3    -------------------- VIN, RESET
GND    -------------------- GND ----------------------- GND
                            SD0 ----------------------- SDA
                            SC0 ----------------------- SCL
3V3    ------------------------------------------------- VIN
3V3    ------------------------------------------------- CS
GND    ------------------------------------------------- SA0   (0x68)
                            (3V3 pin: leave open)
```

### Power and pull-up notes

- The GY-BMI160 has a ME6211 3.3 V LDO and four 3.9 kΩ pull-ups (R1–R4) tied to
  **`VIN`**. Feed `VIN` from 3.3 V; never 5 V, because that would pull SDA, SCL,
  `CS` and `SA0` to 5 V. Leave the `3V3` pin open: it is the LDO output.
- The onboard 3.9 kΩ pull-ups are enough for one sensor. The TCA9548A breakout
  may add 10 kΩ on the trunk; in parallel this is about 2.8 kΩ, fine at
  100 kHz. Do not add 4.7 kΩ on top.
- The TCA9548A does not isolate the upstream bus. With a channel selected, the
  mux still answers at `0x70`; this firmware filters `0x70` out of downstream
  scan results on purpose.

## Build and flash

Install the ESP32 core once:

```bash
arduino-cli core install esp32:esp32
```

From the workspace root (`/Users/rifusaki/localRepos/uni`):

```bash
./invexp/esp320/scripts/flash.sh                 # monitor only; does not touch flash
./invexp/esp320/scripts/flash.sh --flash         # compile, upload, then monitor
./invexp/esp320/scripts/flash.sh --flash --no-monitor
./invexp/esp320/scripts/flash.sh --flash --port /dev/cu.usbmodem5CBC3855071
./invexp/esp320/scripts/monitor.sh               # monitor at 115200, Ctrl-C exits
```

Or from `invexp/esp320`:

```bash
./scripts/flash.sh --flash
./scripts/flash.sh              # monitor only
```

The scripts use FQBN `esp32:esp32:esp32s3` with
`FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB`. On the native USB
port, `flash.sh --flash` adds `CDCOnBoot=cdc` so `Serial` goes to USB; on the
CH343 UART port it keeps `Serial` on UART0. Use `--no-cdc` to disable that. If a
future core changes the valid board options, override them:

```bash
BOARD_OPTIONS="" ./scripts/flash.sh --flash
```

Manual commands, if the helper scripts are not wanted:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 \
  --board-options FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB \
  --warnings all invexp/esp320/firmware/esp32_bmi160_bringup

arduino-cli upload --fqbn esp32:esp32:esp32s3 \
  --board-options FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB \
  --port /dev/cu.usbmodem5CBC3855071 invexp/esp320/firmware/esp32_bmi160_bringup
```

## Serial commands

Commands are single letters, case-insensitive. Line endings are optional.

| Key | Action |
|---|---|
| `s` | Scan the upstream/direct bus (mux channels disabled first) |
| `m` | Scan all eight mux channels, one line per channel, with `0x70` filtered out |
| `d` | Read a BMI160 directly on GPIO8/GPIO9 at `0x68` or `0x69` |
| `0` | Read a BMI160 through mux channel 0 |
| `r` | Start accel + gyro streaming at about 10 Hz |
| `x` | Stop streaming |
| `i` | Print detected configuration, chip IDs, addresses, and sensor status |
| `?` | Print the command menu |

BMI160 configuration used by the firmware:

| Setting | Register | Value |
|---|---|---|
| Soft reset | `0x7E` | `0xB6`, then 100 ms wait |
| Chip ID check | `0x00` | must read `0xD1` |
| Accel range +/-2 g | `0x41` | `0x03` |
| Accel ODR 100 Hz, normal filter | `0x40` | `0x28` |
| Gyro range +/-2000 dps | `0x43` | `0x00` |
| Gyro ODR 100 Hz, normal | `0x42` | `0x28` |
| Accel normal mode | `0x7E` | `0x11`, then 10 ms wait |
| Gyro normal mode | `0x7E` | `0x15`, then 100 ms wait |
| Accel data | `0x12`-`0x17` | little-endian |
| Gyro data | `0x0C`-`0x11` | little-endian |

Scale assumptions printed at boot and on `i`:
`accel_g = raw / 16384.0` and `gyro_dps = raw / 16.4`.

## Expected output

No mux and no sensor connected yet (the normal first flash):

```
[scan] upstream bus: none
[cfg ] TCA9548A at 0x70: not found (direct mode still possible)
[cfg ] direct BMI160 at 0x68/0x69: not found
[fail] BMI160 not found at 0x68/0x69; check CS high, SA0, SDA/SCL, VIN, GND
[fail] no TCA9548A at 0x70 either; check RESET high, A0/A1/A2 to GND
[init] ready. Type ? for commands.
```

Sensor direct at `0x69`:

```
[scan] upstream bus: 0x69 (BMI160)
[cfg ] TCA9548A at 0x70: not found (direct mode still possible)
[cfg ] direct BMI160 at 0x69: ready (chip ID 0xD1)
[bmi ] direct BMI160 at 0x69 ready (chip ID 0xD1)
[cfg ] scales: accel raw/16384.0 -> g (+/-2 g); gyro raw/16.4 -> dps (+/-2000 dps)
```

Mux plus sensor on channel 0:

```
[scan] upstream bus: 0x70 (TCA9548A)
[mux ] CH0: 0x69 (BMI160)
[mux ] CH1: none
...
[mux ] CH7: none
[bmi ] mux CH0 BMI160 at 0x69 ready (chip ID 0xD1)
[cfg ] mux target CH0: BMI160 0x69 ready (chip ID 0xD1)
```

Streaming (`r`):

```
[stream] 10 Hz started: BMI160 0x69 via mux CH0; x stops
[data] accel_g x=+0.001 y=-0.004 z=+0.998 | gyro_dps x=+0.12 y=-0.06 z=+0.03
```

Flat on the table, one axis should read close to +1 g (or -1 g depending on
orientation) and the other two close to 0 g.

## Troubleshooting

### No `/dev/cu.usbmodem*` port

- Use a USB-C **data** cable, not a charge-only cable.
- Replug the board. The CH343 bridge should reappear as
  `/dev/cu.usbmodem...`; it is not a `/dev/tty.usbserial` device.
- If macOS reports no device, check the CH343 driver. The board may also be in a
  bad state after a failed upload; unplug/replug it.
- Close any other program using the port (Arduino IDE monitor, screen, minicom).

### Upload fails or cannot connect

Hold **BOOT** (GPIO0), tap **RESET** (EN) once, release BOOT, then rerun
`./scripts/flash.sh`. The CH343 auto-reset circuit normally handles this; manual
BOOT/RESET is the fallback. If the port vanished, unplug/replug USB first.

### `BMI160 not found at 0x68/0x69`

- `CS` must be tied to 3V3. Low or floating selects SPI mode. R3 on the
  GY-BMI160 already pulls it high, but tie it explicitly.
- `SA0` selects the address: GND = `0x68`; 3.3 V or floating = `0x69`. R4 pulls
  it high by default. The firmware tries both addresses.
- Check SDA to GPIO8 and SCL to GPIO9 (not swapped), and a common GND.
- Verify 3.3 V on BMI `VIN`, not on the `3V3` output pin.
- Confirm the module has I2C pull-ups. The GY-BMI160 has 3.9 kΩ to `VIN`.
- A BMI160 in I2C mode responds only after `CS` is high. Power-cycle after
  fixing `CS`.

### `TCA9548A not found at 0x70`

- `RESET` must be high, directly or through 10 kOhm. A floating RESET can hold
  the mux in reset.
- `A0`, `A1`, `A2` must be at GND for `0x70`.
- Check VIN = 3.3 V and common GND.
- Check upstream SDA/SCL at GPIO8/GPIO9.
- Some mux breakouts label the channel pins `SD0/SC0` or `SDA0/SCL0`; they are
  the same signals.

### Sensor found direct but not on a mux channel

- The sensor must be wired to `SD0`/`SC0` (channel 0), not left on GPIO8/GPIO9.
- Check the mux channel-select read-back with `i`; a channel-select failure is
  reported explicitly.
- Do not bridge two channels together. If two channels show the same sensor,
  inspect the SD/SC wiring for a short.
- The mux itself appears at `0x70` while a channel is selected. The `m` command
  filters it out; if `0x70` ever appears in a `CHn` line, the firmware or the
  wiring is wrong.

### Sensor readings are noisy or the bus locks up

- Use short wires, especially between the mux and the sensor.
- Too many pull-ups in parallel can make edges too fast and cause ringing.
  Remove extra module pull-ups when stacking sensors.
- If SDA is held low, power-cycle everything before rescanning.
- The BMI160 is 3.3 V logic. Do not use 5 V I2C pull-ups; the GY-BMI160 ties
  its 3.9 kΩ pull-ups to `VIN`, so `VIN` must be 3.3 V.

### Monitor shows garbage or the board resets when it opens

On CH343, opening the port with DTR and RTS both asserted holds the board in
reset. `monitor.sh` deasserts both. If you see garbage with another terminal,
disable DTR/RTS or use `monitor.sh`. Tap `RESET` after opening the monitor to
capture the boot banner.

### Monitor connects but shows no output

Check which USB-C port is in use:

- **CH343/UART port**: `Serial` on UART0, VID `0x1A86`.
- **Native USB port**: VID `0x303A`. Needs firmware built with `CDCOnBoot=cdc`;
  `flash.sh --flash` enables it automatically.

Both enumerate as `/dev/cu.usbmodem*`. `monitor.sh` prints which type it detected.
