#!/usr/bin/env python3
"""Generate printable bench-wiring schematics for the ESP32-S3 + BMI160 tests.

Two independent sheets are produced:

1. ``direct_bmi160``          ESP32-S3 -> BMI160, no multiplexer.
2. ``mux_tca9548a_bmi160_ch0`` ESP32-S3 -> TCA9548A -> BMI160 on channel 0.

The script also writes ``netlist.csv`` from the same net table that drives the
documentation, so the drawing, the CSV and WIRING.md share one source of truth.

Run from anywhere::

    pixi run schematic

The workspace root pixi.toml owns the Python dependencies (schemdraw,
matplotlib, Pillow).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

try:
    import schemdraw
    from schemdraw import elements as elm
except ImportError as exc:  # pragma: no cover - environment failure, fail loud
    raise SystemExit(
        "schemdraw is not installed. Run `pixi install` at the workspace root."
    ) from exc

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - environment failure, fail loud
    raise SystemExit(
        "Pillow is not installed. Run `pixi install` at the workspace root."
    ) from exc


SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR
TEST_DATE = date.today().isoformat()
PNG_DPI = 300
MIN_PNG_WIDTH_PX = 2400

# Colour code agreed for the bench test.
COLOR_3V3 = "#C81E1E"      # red
COLOR_GND = "#111111"      # black
COLOR_SDA = "#1D4ED8"      # blue
COLOR_SCL = "#15803D"      # green
COLOR_CONTROL = "#C2410C"  # orange, CS / SA0 / straps
COLOR_NC = "#6B7280"       # grey, leave-open marks
COLOR_BOARD = "#F8FAFC"
COLOR_BOARD_EDGE = "#1E293B"
COLOR_TEXT = "#0F172A"
COLOR_MUTED = "#475569"

# Board geometry, in drawing units. One unit = 0.5 inch (schemdraw config).
SHEET_WIDTH = 25.6
TOP_RAIL_Y = 15.0
BOTTOM_RAIL_Y = 5.2
BOARD_TOP = 14.2
BOARD_BOTTOM = 6.2

ESP_X0, ESP_X1 = 0.8, 6.2
MUX_X0, MUX_X1 = 9.4, 15.0
BMI_X0, BMI_X1 = 19.6, 23.4
STUB = 0.8


@dataclass(frozen=True)
class NetRow:
    """One physical wire or one deliberately unused pin."""

    config: str
    net: str
    from_ref: str
    from_pin: str
    to_ref: str
    to_pin: str
    note: str


DIRECT_NETS = (
    NetRow("direct", "3V3", "ESP32", "3V3", "RAIL_3V3", "+",
           "Feed the breadboard 3V3 rail from the ESP32 3V3 pin."),
    NetRow("direct", "3V3", "RAIL_3V3", "+", "BMI160", "VIN",
           "GY-BMI160: feed VIN from 3.3 V. Its 3.9k pull-ups and LDO input are tied to VIN; 5 V here would put 5 V on SDA/SCL. Leave 3V3 open."),
    NetRow("direct", "3V3", "RAIL_3V3", "+", "BMI160", "CS",
           "CS HIGH selects I2C. Floating or LOW selects SPI and hides the sensor."),
    NetRow("direct", "GND", "RAIL_GND", "-", "BMI160", "SA0",
           "SA0 LOW = 0x68. The onboard R4 pulls SA0 high; this strap overrides it to GND."),
    NetRow("direct", "GND", "ESP32", "GND", "RAIL_GND", "-",
           "Common ground rail; one star point at the ESP32 GND pin."),
    NetRow("direct", "GND", "RAIL_GND", "-", "BMI160", "GND", ""),
    NetRow("direct", "SDA", "ESP32", "GPIO8", "BMI160", "SDA",
           "I2C data. 100 kHz for the first bring-up."),
    NetRow("direct", "SCL", "ESP32", "GPIO9", "BMI160", "SCL",
           "I2C clock."),
    NetRow("direct", "NC", "BMI160", "INT1", "-", "-",
           "Leave open; no wire."),
    NetRow("direct", "NC", "BMI160", "INT2", "-", "-",
           "Leave open; no wire."),
    NetRow("direct", "NC", "BMI160", "3V3", "-", "-",
           "LDO output on the GY-BMI160; leave open when VIN is powered."),
    NetRow("direct", "NC", "BMI160", "SCX", "-", "-",
           "Secondary interface clock; leave open in this test."),
    NetRow("direct", "NC", "BMI160", "SDX", "-", "-",
           "Secondary interface data; leave open in this test."),
    NetRow("direct", "NC", "BMI160", "OCS", "-", "-",
           "Secondary OIS chip select; leave open in this test."),
)

MUX_NETS = (
    NetRow("mux", "3V3", "ESP32", "3V3", "RAIL_3V3", "+",
           "Feed the breadboard 3V3 rail from the ESP32 3V3 pin."),
    NetRow("mux", "3V3", "RAIL_3V3", "+", "MUX", "VIN",
           "Mux supply. 3.3 V."),
    NetRow("mux", "3V3", "RAIL_3V3", "+", "MUX", "RESET",
           "RESET must be HIGH. Do not leave floating."),
    NetRow("mux", "3V3", "RAIL_3V3", "+", "BMI160", "VIN",
           "Sensor supply from the 3V3 rail; the mux switches only SDA/SCL. Pull-ups and LDO input are tied to VIN; leave 3V3 open."),
    NetRow("mux", "3V3", "RAIL_3V3", "+", "BMI160", "CS",
           "CS HIGH selects I2C."),
    NetRow("mux", "GND", "RAIL_GND", "-", "BMI160", "SA0",
           "SA0 LOW = 0x68. The onboard R4 pulls SA0 high; this strap overrides it to GND."),
    NetRow("mux", "GND", "ESP32", "GND", "RAIL_GND", "-",
           "Common ground rail."),
    NetRow("mux", "GND", "RAIL_GND", "-", "MUX", "GND", ""),
    NetRow("mux", "GND", "RAIL_GND", "-", "MUX", "A0",
           "Address strap LOW -> 0x70."),
    NetRow("mux", "GND", "RAIL_GND", "-", "MUX", "A1",
           "Address strap LOW -> 0x70."),
    NetRow("mux", "GND", "RAIL_GND", "-", "MUX", "A2",
           "Address strap LOW -> 0x70."),
    NetRow("mux", "GND", "RAIL_GND", "-", "BMI160", "GND", ""),
    NetRow("mux", "SDA", "ESP32", "GPIO8", "MUX", "SDA",
           "Trunk SDA. The mux is the only device on the ESP32 bus."),
    NetRow("mux", "SCL", "ESP32", "GPIO9", "MUX", "SCL",
           "Trunk SCL."),
    NetRow("mux", "MUX_CH0_SDA", "MUX", "SD0", "BMI160", "SDA",
           "Channel 0 data. Only channel 0 is populated today."),
    NetRow("mux", "MUX_CH0_SCL", "MUX", "SC0", "BMI160", "SCL",
           "Channel 0 clock."),
    *(
        NetRow("mux", "NC", "MUX", f"SD{channel}", "-", "-",
               f"Channel {channel} unused: leave open. SC{channel} also open.")
        for channel in range(1, 8)
    ),
    *(
        NetRow("mux", "NC", "MUX", f"SC{channel}", "-", "-",
               f"Channel {channel} unused: leave open. SD{channel} also open.")
        for channel in range(1, 8)
    ),
    NetRow("mux", "NC", "BMI160", "INT1", "-", "-",
           "Leave open; no wire."),
    NetRow("mux", "NC", "BMI160", "INT2", "-", "-",
           "Leave open; no wire."),
    NetRow("mux", "NC", "BMI160", "3V3", "-", "-",
           "LDO output on the GY-BMI160; leave open when VIN is powered."),
    NetRow("mux", "NC", "BMI160", "SCX", "-", "-",
           "Secondary interface clock; leave open in this test."),
    NetRow("mux", "NC", "BMI160", "SDX", "-", "-",
           "Secondary interface data; leave open in this test."),
    NetRow("mux", "NC", "BMI160", "OCS", "-", "-",
           "Secondary OIS chip select; leave open in this test."),
)


class Sheet:
    """A drawing plus the set of electrical nets that received a label."""

    def __init__(self, title: str, subtitle: str, sheet_number: str) -> None:
        schemdraw.use("matplotlib")
        schemdraw.config(
            unit=2.0,
            inches_per_unit=0.5,
            fontsize=14,
            font="DejaVu Sans",
            lw=2,
            bgcolor="white",
        )
        self.drawing = schemdraw.Drawing()
        self.nets: set[str] = set()
        self._draw_header(title, subtitle, sheet_number)

    # ------------------------------------------------------------------ text
    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        size: float = 12.0,
        color: str = COLOR_TEXT,
        halign: str = "left",
        valign: str = "center",
    ) -> None:
        self.drawing += (
            elm.Label()
            .at((x, y))
            .label(value, fontsize=size, color=color, halign=halign, valign=valign)
        )

    def _draw_header(self, title: str, subtitle: str, sheet_number: str) -> None:
        self.text(0.8, 17.15, title, size=21, halign="left", valign="top")
        self.text(0.8, 16.38, subtitle, size=11.5, color=COLOR_MUTED,
                  halign="left", valign="top")
        self.text(25.0, 16.38, sheet_number, size=11.5, color=COLOR_MUTED,
                  halign="right", valign="top")
        self.drawing += (
            elm.Line()
            .at((0.8, 16.05))
            .to((25.0, 16.05))
            .color("#94A3B8")
            .linewidth(1.2)
        )

    # ----------------------------------------------------------------- boards
    def board(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        title: str,
        subtitle: str,
    ) -> None:
        self.drawing += (
            elm.Rect(corner1=(x0, y0), corner2=(x1, y1), fill=COLOR_BOARD)
            .theta(0)
            .at((0, 0))
            .color(COLOR_BOARD_EDGE)
            .linewidth(2.0)
        )
        centre_x = (x0 + x1) / 2
        self.text(centre_x, y0 + 1.35, title, size=13.5, halign="center")
        self.text(centre_x, y0 + 0.80, subtitle, size=9.5, color=COLOR_MUTED,
                  halign="center")

    def pin(
        self,
        x: float,
        y: float,
        side: str,
        name: str,
        *,
        color: str = COLOR_TEXT,
        length: float = STUB,
    ) -> tuple[float, float]:
        """Draw one labelled pin and return the outer end of its stub."""
        if side == "left":
            end = (x - length, y)
            self.drawing += elm.Line().at((x, y)).to(end).color("#64748B").linewidth(2.0)
            self.text(x + 0.16, y, name, size=12.5, color=color, halign="left")
        elif side == "right":
            end = (x + length, y)
            self.drawing += elm.Line().at((x, y)).to(end).color("#64748B").linewidth(2.0)
            self.text(x - 0.16, y, name, size=12.5, color=color, halign="right")
        elif side == "top":
            end = (x, y + length)
            self.drawing += elm.Line().at((x, y)).to(end).color("#64748B").linewidth(2.0)
            self.text(x, y - 0.16, name, size=12.5, color=color,
                      halign="center", valign="top")
        elif side == "bottom":
            end = (x, y - length)
            self.drawing += elm.Line().at((x, y)).to(end).color("#64748B").linewidth(2.0)
            self.text(x, y + 0.16, name, size=12.5, color=color,
                      halign="center", valign="bottom")
        else:
            raise ValueError(f"unknown pin side {side!r}")
        return end

    # ------------------------------------------------------------------ wires
    def wire(
        self,
        points: list[tuple[float, float]],
        net: str,
        color: str,
        *,
        label_at: tuple[float, float] | None = None,
        label: str | None = None,
        label_size: float = 11.5,
        halign: str = "center",
        valign: str = "bottom",
        width: float = 2.4,
    ) -> None:
        if len(points) < 2:
            raise ValueError(f"net {net!r} needs at least two points")
        for start, end in zip(points, points[1:]):
            self.drawing += (
                elm.Line().at(start).to(end).color(color).linewidth(width)
            )
        self.nets.add(net)
        if label_at is not None:
            self.text(
                label_at[0],
                label_at[1],
                label or net,
                size=label_size,
                color=color,
                halign=halign,
                valign=valign,
            )

    def junction(self, x: float, y: float, color: str) -> None:
        self.drawing += elm.Dot(radius=0.10).at((x, y)).color(color)

    def nc(self, x: float, y: float, net: str = "NC") -> None:
        """Draw a small no-connect cross."""
        size = 0.13
        self.drawing += elm.Line().at((x - size, y - size)).to((x + size, y + size)) \
            .color(COLOR_NC).linewidth(1.6)
        self.drawing += elm.Line().at((x - size, y + size)).to((x + size, y - size)) \
            .color(COLOR_NC).linewidth(1.6)
        self.nets.add(net)

    # --------------------------------------------------------------- extras
    def rail(self, y: float, x0: float, x1: float, net: str, color: str,
             label: str, label_x: float) -> None:
        self.drawing += elm.Line().at((x0, y)).to((x1, y)).color(color).linewidth(3.2)
        self.text(label_x, y + 0.16, label, size=10.5, color=color,
                  halign="center", valign="bottom")
        self.nets.add(net)

    def warning_box(self) -> None:
        self.drawing += (
            elm.Rect(corner1=(0.8, 0.30), corner2=(25.0, 1.50), fill="#FFF1F2")
            .theta(0)
            .at((0, 0))
            .color("#B91C1C")
            .linewidth(2.2)
        )
        self.text(1.1, 1.16,
                  "USB connected? Verify 3V3-GND is NOT shorted before plugging in.",
                  size=12.5, color="#991B1B", halign="left", valign="top")
        self.text(1.1, 0.68,
                  "Unplug USB before changing wires. Direct and mux configurations are alternatives - never wire both.",
                  size=10.5, color="#991B1B", halign="left", valign="top")

    def optional_panel(
        self,
        x0: float,
        x1: float,
        y0: float,
        y1: float,
        *,
        pull_up_note: str = "one pair on the bus only (already onboard)",
        decoupling: tuple[tuple[str, str, str], ...],
    ) -> None:
        """Draw optional pull-ups plus the requested decoupling capacitors.

        ``decoupling`` items are (value, bottom_net, caption) and are always
        drawn between 3V3 and the given bottom net.
        """
        self.drawing += (
            elm.Rect(corner1=(x0, y0), corner2=(x1, y1), fill="#FFFBEB")
            .theta(0)
            .at((0, 0))
            .color("#D97706")
            .linewidth(1.0)
            .linestyle("--")
        )
        self.text(x0 + 0.2, y1 - 0.16,
                  f"OPTIONAL - not needed for first power-up. Pull-ups: {pull_up_note}.",
                  size=9.0, color="#92400E", halign="left", valign="top")

        slots = x1 - x0 - 0.6
        items = 2 + len(decoupling)
        step = slots / items
        centres = [x0 + 0.3 + step * (index + 0.5) for index in range(items)]

        for index, centre in enumerate(centres[:2]):
            bottom_net = ("SDA", "SCL")[index]
            bottom_color = (COLOR_SDA, COLOR_SCL)[index]
            self._passive(centre, "Resistor", "4.7k", bottom_net, bottom_color,
                          "pull-up")
        for centre, (value, bottom_net, caption) in zip(centres[2:], decoupling):
            self._passive(centre, "Capacitor", value, bottom_net, COLOR_GND, caption)

    def _passive(self, x: float, kind: str, value: str, bottom_net: str,
                 bottom_color: str, caption: str) -> None:
        top_y, bottom_y = 3.68, 2.88
        self.text(x, top_y + 0.14, "3V3", size=8.0, color=COLOR_3V3,
                  halign="center", valign="bottom")
        element = elm.Resistor() if kind == "Resistor" else elm.Capacitor()
        self.drawing += (
            element.at((x, top_y)).to((x, bottom_y)).color(COLOR_TEXT).linewidth(1.8)
        )
        self.text(x + 0.22, (top_y + bottom_y) / 2, value, size=7.5,
                  color=COLOR_MUTED, halign="left")
        self.text(x, bottom_y - 0.10, bottom_net, size=8.0, color=bottom_color,
                  halign="center", valign="top")
        self.text(x, 2.45, caption, size=7.5, color=COLOR_MUTED, halign="center")

    def notes_panel(self, x0: float, x1: float, y0: float, y1: float,
                    heading: str, lines: tuple[str, ...]) -> None:
        self.drawing += (
            elm.Rect(corner1=(x0, y0), corner2=(x1, y1), fill="#EFF6FF")
            .theta(0)
            .at((0, 0))
            .color("#2563EB")
            .linewidth(1.0)
        )
        self.text(x0 + 0.2, y1 - 0.16, heading, size=9.5, color="#1E3A8A",
                  halign="left", valign="top")
        line_y = y1 - 0.62
        for line in lines:
            self.text(x0 + 0.2, line_y, line, size=8.6, color="#1E3A8A",
                      halign="left", valign="top")
            line_y -= 0.48

    # ------------------------------------------------------------------ save
    def save(self, stem: str) -> list[Path]:
        outputs: list[Path] = []
        for extension in ("svg", "png", "pdf"):
            path = OUTPUT_DIR / f"{stem}.{extension}"
            self.drawing.save(str(path), dpi=PNG_DPI, transparent=False)
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError(f"renderer produced no data for {path}")
            outputs.append(path)
        _verify_png(outputs[1])
        _verify_svg(outputs[0])
        _verify_pdf(outputs[2])
        return outputs


def _verify_png(path: Path) -> None:
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        width, height = image.size
        if width < MIN_PNG_WIDTH_PX or height < MIN_PNG_WIDTH_PX:
            raise RuntimeError(f"{path.name} is unexpectedly small: {width}x{height}px")


def _verify_svg(path: Path) -> None:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise RuntimeError(f"{path.name} is not valid XML: {exc}") from exc
    if not root.tag.endswith("svg"):
        raise RuntimeError(f"{path.name} root element is not <svg>")


def _verify_pdf(path: Path) -> None:
    with path.open("rb") as handle:
        if handle.read(4) != b"%PDF":
            raise RuntimeError(f"{path.name} does not start with %PDF")


def _esp32(sheet: Sheet) -> None:
    sheet.board(ESP_X0, BOARD_BOTTOM, ESP_X1, BOARD_TOP,
                "ESP32-S3 DevKitC-1", "N16R8 - USB-C to PC")
    sheet.text((ESP_X0 + ESP_X1) / 2, 6.72,
               "USB provides power, flashing and serial.",
               size=8.8, color=COLOR_MUTED, halign="center")
    sheet.pin(ESP_X1, 13.8, "right", "3V3", color=COLOR_3V3)
    sheet.pin(ESP_X1, 12.6, "right", "SDA / GPIO8", color=COLOR_SDA)
    sheet.pin(ESP_X1, 11.6, "right", "SCL / GPIO9", color=COLOR_SCL)
    sheet.pin(ESP_X1, 9.0, "right", "GND", color=COLOR_GND)


def _bmi160(sheet: Sheet, *, include_nc: bool) -> None:
    sheet.board(BMI_X0, BOARD_BOTTOM, BMI_X1, BOARD_TOP,
                "GY-BMI160 breakout", "3-axis accel + gyro")
    sheet.text((BMI_X0 + BMI_X1) / 2, 6.70,
               "CS high = I2C. SA0 sets address.",
               size=8.8, color=COLOR_MUTED, halign="center")
    sheet.text((BMI_X0 + BMI_X1) / 2, 8.35,
               "3V3 = LDO output; SCX, SDX, OCS: open",
               size=8.2, color=COLOR_MUTED, halign="center")
    sheet.pin(BMI_X0, 13.8, "left", "VIN", color=COLOR_3V3)
    sheet.pin(BMI_X0, 12.6, "left", "SDA", color=COLOR_SDA)
    sheet.pin(BMI_X0, 11.6, "left", "SCL", color=COLOR_SCL)
    sheet.pin(BMI_X1, 13.0, "right", "CS", color=COLOR_CONTROL)
    sheet.pin(BMI_X1, 12.0, "right", "SA0", color=COLOR_CONTROL)
    sheet.pin(BMI_X1, 10.6, "right", "INT1", color=COLOR_NC)
    sheet.pin(BMI_X1, 9.6, "right", "INT2", color=COLOR_NC)
    sheet.pin((BMI_X0 + BMI_X1) / 2, BOARD_BOTTOM, "bottom", "GND", color=COLOR_GND)

    if include_nc:
        sheet.nc(BMI_X1 + STUB + 0.20, 10.6)
        sheet.nc(BMI_X1 + STUB + 0.20, 9.6)
        sheet.text(BMI_X1 + STUB + 0.44, 10.1, "NC", size=9.0,
                   color=COLOR_NC, halign="left")


def _build_direct() -> Sheet:
    sheet = Sheet(
        "BMI160 direct to ESP32-S3 - bench wiring",
        f"Sheet 1 of 2 - direct I2C, no multiplexer - {TEST_DATE} - ESP32-S3 DevKitC-1 N16R8 - 100 kHz",
        "DIRECT / 0x68-0x69",
    )
    _esp32(sheet)
    _bmi160(sheet, include_nc=True)

    # 3V3 rail: ESP feed, BMI VIN, then CS/SA0 on the right-hand bus.
    sheet.rail(TOP_RAIL_Y, 7.0, 24.4, "3V3", COLOR_3V3,
               "3V3 RAIL (from ESP32 3V3)", 12.6)
    sheet.wire([(7.0, 13.8), (7.0, TOP_RAIL_Y)], "3V3", COLOR_3V3,
               label_at=(7.18, 14.55), label="3V3", halign="left")
    sheet.wire([(18.8, 13.8), (18.4, 13.8), (18.4, TOP_RAIL_Y)], "3V3", COLOR_3V3,
               label_at=(18.55, 14.45), label="VIN", halign="left")
    sheet.junction(18.4, TOP_RAIL_Y, COLOR_3V3)

    sheet.wire([(24.2, 13.0), (24.4, 13.0), (24.4, TOP_RAIL_Y)], "3V3", COLOR_3V3)
    sheet.wire([(24.2, 12.0), (24.8, 12.0), (24.8, BOTTOM_RAIL_Y)], "GND", COLOR_GND,
               label_at=(24.62, 11.80), label="GND", halign="right")

    # Ground rail.
    sheet.rail(BOTTOM_RAIL_Y, 7.0, 24.8, "GND", COLOR_GND,
               "GND RAIL (common)", 13.8)
    sheet.junction(20.6, BOTTOM_RAIL_Y, COLOR_GND)
    sheet.wire([(7.0, 9.0), (7.0, BOTTOM_RAIL_Y)], "GND", COLOR_GND,
               label_at=(7.18, 7.10), label="GND", halign="left")
    sheet.wire([(20.6, BOARD_BOTTOM - STUB), (20.6, BOTTOM_RAIL_Y)], "GND", COLOR_GND,
               label_at=(20.78, 5.82), label="GND", halign="left")

    # Signal wires, straight across the gap.
    sheet.wire([(7.0, 12.6), (18.8, 12.6)], "SDA", COLOR_SDA,
               label_at=(12.9, 12.76), label="SDA")
    sheet.wire([(7.0, 11.6), (18.8, 11.6)], "SCL", COLOR_SCL,
               label_at=(12.9, 11.76), label="SCL")

    sheet.text(12.9, 13.35, "SA0 -> 3V3 = 0x69   |   SA0 -> GND = 0x68",
               size=9.5, color=COLOR_CONTROL, halign="center")
    sheet.text(12.9, 10.95, "CS floating or GND = SPI mode, sensor invisible on I2C.",
               size=9.0, color=COLOR_MUTED, halign="center")

    sheet.optional_panel(
        0.8, 13.4, 1.80, 4.55,
        decoupling=(
            ("100nF", "GND", "at ESP32 3V3"),
            ("100nF", "GND", "at BMI160 VIN"),
            ("10uF", "GND", "bulk on 3V3 rail"),
        ),
    )
    sheet.notes_panel(
        14.0, 25.0, 1.80, 4.55,
        "BEFORE YOU POWER UP",
        (
            "SA0 -> 3V3: 0x69. SA0 -> GND: 0x68. Pick one, not both.",
            "CS must be HIGH; otherwise the BMI160 speaks SPI.",
            "Start at 100 kHz. 400 kHz only after stable reads.",
            "INT1 / INT2: leave open (no wires).",
            "This sheet is an ALTERNATIVE to the mux sheet.",
        ),
    )
    sheet.warning_box()
    return sheet


def _mux_board(sheet: Sheet) -> None:
    sheet.board(MUX_X0, BOARD_BOTTOM, MUX_X1, BOARD_TOP,
                "TCA9548A mux", "1-to-8 I2C, address 0x70")
    sheet.text((MUX_X0 + MUX_X1) / 2, 9.95,
               "CH1-CH7: leave open",
               size=10.5, color=COLOR_NC, halign="center")
    sheet.text((MUX_X0 + MUX_X1) / 2, 9.42,
               "SD1/SC1 ... SD7/SC7",
               size=8.8, color=COLOR_NC, halign="center")
    sheet.text((MUX_X0 + MUX_X1) / 2, 8.92,
               "do not fit wires on unused channels",
               size=8.0, color=COLOR_NC, halign="center")

    # Control side (left) and supply pins.
    sheet.pin(MUX_X0, 12.6, "left", "SDA", color=COLOR_SDA)
    sheet.pin(MUX_X0, 11.6, "left", "SCL", color=COLOR_SCL)
    sheet.pin(MUX_X0, 9.0, "left", "A0", color=COLOR_CONTROL)
    sheet.pin(MUX_X0, 8.0, "left", "A1", color=COLOR_CONTROL)
    sheet.pin(MUX_X0, 7.0, "left", "A2", color=COLOR_CONTROL)
    sheet.pin(10.4, BOARD_TOP, "top", "VIN", color=COLOR_3V3)
    sheet.pin(12.0, BOARD_TOP, "top", "RESET", color=COLOR_CONTROL)
    sheet.pin(11.2, BOARD_BOTTOM, "bottom", "GND", color=COLOR_GND)

    # Channel 0 only.
    sheet.pin(MUX_X1, 13.0, "right", "SD0", color=COLOR_SDA)
    sheet.pin(MUX_X1, 12.0, "right", "SC0", color=COLOR_SCL)
    sheet.text(MUX_X1 - 0.16, 11.30, "SD1...SD7 / SC1...SC7: open",
               size=8.2, color=COLOR_NC, halign="right")


def _build_mux() -> Sheet:
    sheet = Sheet(
        "TCA9548A mux + BMI160 on channel 0 - bench wiring",
        f"Sheet 2 of 2 - mux is the only device on the ESP32 bus - {TEST_DATE} - ESP32-S3 DevKitC-1 N16R8 - 100 kHz",
        "MUX / 0x70 + 0x68-0x69",
    )
    _esp32(sheet)
    _mux_board(sheet)
    _bmi160(sheet, include_nc=True)

    sheet.rail(TOP_RAIL_Y, 7.0, 24.4, "3V3", COLOR_3V3,
               "3V3 RAIL (from ESP32 3V3)", 7.8)
    sheet.wire([(7.0, 13.8), (7.0, TOP_RAIL_Y)], "3V3", COLOR_3V3,
               label_at=(7.18, 14.55), label="3V3", halign="left")

    # Mux supply and reset straps.
    sheet.wire([(10.4, BOARD_TOP + STUB), (10.4, TOP_RAIL_Y)], "3V3", COLOR_3V3,
               label_at=(10.55, 15.18), label="VIN", halign="left", label_size=8.5)
    sheet.junction(10.4, TOP_RAIL_Y, COLOR_3V3)
    sheet.wire([(12.0, BOARD_TOP + STUB), (12.0, TOP_RAIL_Y)], "3V3", COLOR_3V3,
               label_at=(12.15, 15.18), label="RESET (HIGH)", halign="left",
               label_size=8.5)
    sheet.junction(12.0, TOP_RAIL_Y, COLOR_3V3)

    # BMI supply and CS/SA0 straps.
    sheet.wire([(18.8, 13.8), (18.2, 13.8), (18.2, TOP_RAIL_Y)], "3V3", COLOR_3V3,
               label_at=(18.35, 14.50), label="VIN", halign="left")
    sheet.junction(18.2, TOP_RAIL_Y, COLOR_3V3)
    sheet.wire([(24.2, 13.0), (24.4, 13.0), (24.4, TOP_RAIL_Y)], "3V3", COLOR_3V3)
    sheet.wire([(24.2, 12.0), (24.8, 12.0), (24.8, BOTTOM_RAIL_Y)], "GND", COLOR_GND,
               label_at=(24.62, 11.80), label="GND", halign="right")

    # Ground rail + A0/A1/A2 straps.
    sheet.rail(BOTTOM_RAIL_Y, 7.0, 24.8, "GND", COLOR_GND,
               "GND RAIL (common)", 15.0)
    sheet.junction(11.2, BOTTOM_RAIL_Y, COLOR_GND)
    sheet.junction(20.6, BOTTOM_RAIL_Y, COLOR_GND)
    sheet.wire([(7.0, 9.0), (7.0, BOTTOM_RAIL_Y)], "GND", COLOR_GND,
               label_at=(7.18, 7.10), label="GND", halign="left")
    sheet.wire([(11.2, BOARD_BOTTOM - STUB), (11.2, BOTTOM_RAIL_Y)], "GND", COLOR_GND,
               label_at=(11.38, 5.72), label="GND", halign="left")
    sheet.wire([(20.6, BOARD_BOTTOM - STUB), (20.6, BOTTOM_RAIL_Y)], "GND", COLOR_GND,
               label_at=(20.78, 5.82), label="GND", halign="left")

    sheet.wire([(8.6, 9.0), (8.2, 9.0), (8.2, BOTTOM_RAIL_Y)], "GND", COLOR_GND,
               label_at=(7.95, 5.45), label="GND", halign="right")
    sheet.wire([(8.6, 8.0), (8.2, 8.0)], "GND", COLOR_GND)
    sheet.wire([(8.6, 7.0), (8.2, 7.0)], "GND", COLOR_GND)
    sheet.junction(8.2, 8.0, COLOR_GND)
    sheet.junction(8.2, 7.0, COLOR_GND)
    sheet.junction(8.2, BOTTOM_RAIL_Y, COLOR_GND)

    # Trunk I2C: ESP32 to mux only.
    sheet.wire([(7.0, 12.6), (8.6, 12.6)], "SDA", COLOR_SDA,
               label_at=(7.80, 12.76), label="SDA", label_size=10.5)
    sheet.wire([(7.0, 11.6), (8.6, 11.6)], "SCL", COLOR_SCL,
               label_at=(7.80, 11.76), label="SCL", label_size=10.5)
    sheet.text(8.0, 10.55, "mux is the ONLY device\non this bus", size=8.2,
               color=COLOR_MUTED, halign="center")

    # Channel 0: mux SD0/SC0 to the sole BMI160.
    sheet.wire([(15.8, 13.0), (17.6, 13.0), (17.6, 12.6), (18.8, 12.6)],
               "MUX_CH0_SDA", COLOR_SDA,
               label_at=(16.55, 13.16), label="MUX_CH0_SDA", label_size=9.8)
    sheet.wire([(15.8, 12.0), (17.1, 12.0), (17.1, 11.6), (18.8, 11.6)],
               "MUX_CH0_SCL", COLOR_SCL,
               label_at=(16.30, 12.16), label="MUX_CH0_SCL", label_size=9.8)

    sheet.text(16.9, 10.45,
               "Only channel 0 is populated today.",
               size=8.8, color=COLOR_MUTED, halign="center")

    sheet.optional_panel(
        0.8, 13.4, 1.80, 4.55,
        pull_up_note="trunk only if the mux board has none",
        decoupling=(
            ("100nF", "GND", "at mux VIN"),
            ("100nF", "GND", "at BMI160 VIN"),
            ("10uF", "GND", "bulk on 3V3 rail"),
        ),
    )
    sheet.notes_panel(
        14.0, 25.0, 1.80, 4.55,
        "BEFORE YOU POWER UP",
        (
            "Mux = 0x70 only when A0, A1 and A2 are all GND.",
            "RESET must be HIGH (3V3); floating resets the mux.",
            "CH0 only: SD0/SC0 -> BMI160 SDA/SCL.",
            "CH1-CH7: SD1/SC1 ... SD7/SC7 leave open.",
            "Do NOT wire the direct sensor at the same time.",
        ),
    )
    sheet.warning_box()
    return sheet


def _write_netlist(rows: tuple[NetRow, ...], path: Path) -> None:
    if not rows:
        raise ValueError("refusing to write an empty netlist")
    fieldnames = ["config", "net", "from_ref", "from_pin", "to_ref", "to_pin", "note"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "config": row.config,
                "net": row.net,
                "from_ref": row.from_ref,
                "from_pin": row.from_pin,
                "to_ref": row.to_ref,
                "to_pin": row.to_pin,
                "note": row.note,
            })


def _assert_drawing_matches_netlist(sheet: Sheet, rows: tuple[NetRow, ...]) -> None:
    expected = {row.net for row in rows}
    if sheet.nets != expected:
        missing = sorted(expected - sheet.nets)
        extra = sorted(sheet.nets - expected)
        raise RuntimeError(
            f"drawing/netlist mismatch for {rows[0].config}: "
            f"missing from drawing {missing}, extra in drawing {extra}"
        )


def main() -> int:
    if not OUTPUT_DIR.is_dir():
        raise SystemExit(f"output directory does not exist: {OUTPUT_DIR}")

    written: list[Path] = []
    for builder, stem, rows in (
        (_build_direct, "direct_bmi160", DIRECT_NETS),
        (_build_mux, "mux_tca9548a_bmi160_ch0", MUX_NETS),
    ):
        sheet = builder()
        _assert_drawing_matches_netlist(sheet, rows)
        written.extend(sheet.save(stem))

    netlist_path = OUTPUT_DIR / "netlist.csv"
    _write_netlist(DIRECT_NETS + MUX_NETS, netlist_path)
    if not netlist_path.is_file() or netlist_path.stat().st_size == 0:
        raise RuntimeError(f"netlist was not written: {netlist_path}")
    written.append(netlist_path)

    print("Generated:")
    for path in written:
        print(f"  {path.name:38s} {path.stat().st_size:9d} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
