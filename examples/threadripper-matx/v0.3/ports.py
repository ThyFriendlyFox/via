"""The ports and headers a modern board carries, and the parts behind them.

    top edge      ARGB header, 12 V RGB header, power and reset buttons
    beside it     CPU_FAN, CPU_OPT and PUMP headers; 4 status LEDs
    right column  the board controller (STM32G0B1), the fan controller (EMC2305), the BIOS flash,
                  the USB 3 front header, SYS_FAN1
    bottom right  4 SATA ports on the right edge, the CMOS battery and its clear jumper
    bottom edge   the front panel header, the USB 2.0 header, SYS_FAN2, the TPM header

The board controller is the board's own: a USB device of the host (as the RGB controllers of
desktop boards are), the SMBus master of the fan controller, and the driver of the RGB headers and
the status LEDs. Its pins are ST's (STM32_open_pin_data, STM32G0B1K(B-C-E)Tx.xml); README.md,
"Pin plan". What reaches the processor (SPI to the flash and the TPM, USB to the headers and the
controller, SATA, the buttons, VBAT) is joined with the processor's slow signals in a later
version; here each such pin is left open or on its local net.

Positions are mech.py's frame. Every supply pin of a surface part gets a via of its own to its
plane (`tap`); a through-hole pin joins its plane or pour on its own.
"""

from __future__ import annotations

import math

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
LED0603 = "LED_SMD:LED_0603_1608Metric"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
SOT23_5 = "Package_TO_SOT_SMD:SOT-23-5"
FAN = "Connector:FanPinHeader_1x04_P2.54mm_Vertical"
H1x4 = "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
H1x2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
H2x5 = "Connector_PinHeader_2.54mm:PinHeader_2x05_P2.54mm_Vertical"
H2x7 = "Connector_PinHeader_2.54mm:PinHeader_2x07_P2.54mm_Vertical"
H2x10 = "Connector_PinHeader_2.00mm:PinHeader_2x10_P2.00mm_Vertical"
BUTTON = "Button_Switch_SMD:SW_Push_1P1T_NO_CK_KSC6xxG"
CR2032 = "Battery:BatteryHolder_Keystone_3034_1x20mm"
LQFP32 = "Package_QFP:LQFP-32_7x7mm_P0.8mm"
QFN16 = "Package_DFN_QFN:QFN-16-1EP_4x4mm_P0.65mm_EP2.1x2.1mm_ThermalVias"  # KiCad has its body
SOIC8 = "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm"  # the 208 mil package, W25Q128JVSIQ
PAD = "TestPoint:TestPoint_Pad_D1.0mm"

# The board controller's pins (LQFP-32), each with its function; README.md, "Pin plan".
MCU = {
    "4": "+3V3",  # VDD
    "5": "GND",  # VSS
    "6": "MCU_NRST",  # PF2-NRST
    "9": "ARGB_DIN",  # PA2: SPI1_MOSI, the ARGB stream at 2.4 Mbit/s, 3 bits a bit
    "13": "RGB_G_PWM",  # PA6: TIM3_CH1
    "14": "RGB_R_PWM",  # PA7: TIM3_CH2
    "15": "RGB_B_PWM",  # PB0: TIM3_CH3
    "16": "LED_CPU",  # PB1
    "17": "LED_DRAM",  # PB2
    "18": "LED_VGA",  # PA8
    "26": "LED_BOOT",  # PA15
    "24": "MCU_SWDIO",  # PA13: SYS_SWDIO
    "25": "MCU_SWCLK",  # PA14: SYS_SWCLK
    "29": "FAN_ALERT",  # PB5: EXTI5, the fan controller's alert
    "30": "SMB_SCL",  # PB6: I2C1_SCL
    "31": "SMB_SDA",  # PB7: I2C1_SDA
}
FANS = ["PUMP", "CPU_OPT", "CPU_FAN", "SYS_FAN1", "SYS_FAN2"]  # EMC2305 channels 1 to 5, by side
# EMC2305 (Microchip DS20006532A): ADDR_SEL reads a pull-up at power-up, 10k to 3.3 V is address
# 0x2C (Table 5-1); CLK is an input at power-up and the datasheet gives no termination for it unused,
# so 10k to ground keeps it from floating; the exposed pad is ground.
EMC = {"1": "SMB_SDA", "2": "SMB_SCL", "3": "+3V3", "4": "EMC_ADDR", "11": "EMC_CLK", "12": "FAN_ALERT", "17": "GND"}
for _i, (_pwm, _tach) in enumerate((("5", "6"), ("7", "8"), ("9", "10"), ("13", "14"), ("15", "16"))):
    EMC[_pwm], EMC[_tach] = f"{FANS[_i]}_PWM", f"{FANS[_i]}_TACH"

# Where each part stands: (u, v, turn). The fan controller is turned 180 so each side faces what it
# drives: its top side the PUMP and CPU_OPT headers, its left the CPU_FAN, its bottom the 2 system
# fans, its right the board controller. The board controller is turned 180 too, its RGB and ARGB
# pins facing the RGB parts above it.
AT = {
    "J19": (174.0, 7.0, 90),  # ARGB, pins along the edge
    "J20": (186.0, 7.0, 90),  # 12 V RGB
    "SW1": (203.0, 7.5, 0),  # power
    "SW2": (217.0, 7.5, 0),  # reset
    "U6": (226.0, 22.0, 0),  # the standby regulator
    "J21": (174.0, 26.0, 0),  # CPU_FAN
    "J22": (187.0, 26.0, 0),  # CPU_OPT
    "J23": (200.0, 26.0, 0),  # PUMP
    "U3": (190.0, 40.0, 180),  # fan controller
    "U2": (208.0, 48.0, 180),  # board controller
    "U4": (177.0, 46.0, 0),  # BIOS flash
    "J25": (207.0, 84.0, 0),  # SYS_FAN1, under the fan controller and clear of the legend
    "J24": (224.0, 122.0, 180),  # USB 3 front header
    "BT1": (196.0, 214.0, 0),  # CMOS battery
    "J31": (174.0, 220.0, 90),  # CLR_CMOS
    "J33": (176.0, 240.0, 90),  # USB 2.0 header
    "J32": (194.0, 240.0, 90),  # front panel
    "J34": (210.0, 239.0, 0),  # SYS_FAN2
    "J35": (140.0, 240.0, 90),  # TPM
    # 4 SATA ports on the right edge, their faces flush with it: 3 below the 24-pin, 1 below M.2_2.
    "J36": (233.13, 105.0, 270),
    "J37": (233.13, 124.0, 270),
    "J38": (233.13, 143.0, 270),
    "J39": (233.13, 210.0, 270),
}
SPINE_U = 229.0  # the +5V spine on In6, from the 24-pin down the right side
FOOT_V = 232.0  # and along the bottom to the USB 2.0 header


def build(d, at, add) -> set[str]:
    """Every part, its nets and the supply copper; returns the nets the router joins."""
    mine: list[str] = []

    def put(ref, lib, value, fp, nets, uv=None, r=None):
        u, v, turn = AT[ref] if uv is None else (*uv, r or 0)
        mine.append(ref)
        return add(ref, lib, value, fp, (u, v), nets, turn)

    def passive(ref, kind, value, n1, n2, uv, r=0, fp=None):
        lib = {"R": "Device:R", "C": "Device:C", "D": "Device:LED"}[kind]
        fp = fp or {"R": R0402, "C": C0402, "D": LED0603}[kind]
        return put(ref, lib, value, fp, {"1": n1, "2": n2}, uv, r)

    # ---- the board controller and what it drives --------------------------------------------------
    put("U2", "MCU_ST_STM32G0:STM32G0B1KBTx", "STM32G0B1KBT6", LQFP32, MCU)
    passive("C300", "C", "100n", "+3V3", "GND", (218.5, 47.0), 0)
    passive("C301", "C", "4.7u", "+3V3", "GND", (218.5, 49.5), 0, C0603)
    passive("C302", "C", "100n", "MCU_NRST", "GND", (218.5, 44.5), 0)
    for i, net in enumerate(("MCU_SWDIO", "MCU_SWCLK", "MCU_NRST", "GND")):
        put(f"TP{i + 1}", "Connector:TestPoint", net.replace("MCU_", ""), PAD, {"1": net}, (203.5 + 3.0 * i, 61.5))
    # ARGB: the controller's 3.3 V stream through a 5 V buffer and 33 ohm to the header's DIN.
    put("U5", "74xGxx:74AHCT1G125", "74AHCT1G125", SOT23_5,
        {"1": "GND", "2": "ARGB_DIN", "3": "GND", "4": "ARGB_BUF", "5": "+5V"}, (178.5, 16.5))
    passive("R300", "R", "33", "ARGB_BUF", "ARGB_DATA", (182.5, 16.0), 90)
    passive("C303", "C", "100n", "+5V", "GND", (175.0, 17.0), 90)
    put("J19", "Basalt:ARGB_HEADER", "ARGB_5V", "Basalt:PinHeader_1x04_Key3",
        {"1": "+5V", "2": "ARGB_DATA", "4": "GND"})
    # 12 V RGB: each colour's cathodes switched to ground by an N-MOSFET, 100 ohm into its gate and
    # 100k holding it off while the controller resets.
    put("J20", "Connector_Generic:Conn_01x04", "RGB_12V", H1x4, {"1": "+12V", "2": "RGB_G", "3": "RGB_R", "4": "RGB_B"})
    for i, c in enumerate("GRB"):
        u = 188.5 + 4.5 * i
        put(f"Q{15 + i}", "Transistor_FET:AO3400A", "AO3400A", SOT23,
            {"1": f"RGB_{c}_G", "2": "GND", "3": f"RGB_{c}"}, (u, 15.8))
        passive(f"R{301 + i}", "R", "100", f"RGB_{c}_PWM", f"RGB_{c}_G", (u - 0.8, 19.8), 0)
        passive(f"R{304 + i}", "R", "100k", f"RGB_{c}_G", "GND", (u + 1.6, 19.8), 90)
    # Status LEDs: each from a controller pin through 1k to ground.
    for i, name in enumerate(("CPU", "DRAM", "VGA", "BOOT")):
        u = 202.0 + 3.0 * i
        passive(f"D{1 + i}", "D", name, f"LED_{name}_K", "GND", (u, 34.5), 90)
        passive(f"R{310 + i}", "R", "1k", f"LED_{name}", f"LED_{name}_K", (u, 38.0), 90)

    # ---- the fan controller and the 5 fan headers ------------------------------------------------------
    put("U3", "Driver_Motor:EMC2305-x-AP", "EMC2305-1-AP", QFN16, EMC)
    passive("C304", "C", "100n", "+3V3", "GND", (194.5, 36.0), 0)
    passive("R320", "R", "4.7k", "SMB_SCL", "+3V3", (208.4, 57.0), 270)  # pin 1 toward the controller, its supply via away
    passive("R321", "R", "4.7k", "SMB_SDA", "+3V3", (211.2, 57.0), 270)
    passive("R322", "R", "10k", "FAN_ALERT", "+3V3", (186.0, 44.5), 0)
    passive("R328", "R", "10k", "EMC_ADDR", "+3V3", (196.5, 37.5), 90)
    passive("R329", "R", "10k", "EMC_CLK", "GND", (186.0, 42.5), 0)
    for i, name in enumerate(FANS):
        ref = {"CPU_FAN": "J21", "CPU_OPT": "J22", "PUMP": "J23", "SYS_FAN1": "J25", "SYS_FAN2": "J34"}[name]
        put(ref, "Motor:Fan_4pin", name, FAN, {"1": "GND", "2": "+12V", "3": f"{name}_TACH", "4": f"{name}_PWM"})
        # The tach is the fan's open collector: 10k to 3.3 V at the controller.
        hu, hv, _ = AT[ref]
        passive(f"R{323 + i}", "R", "10k", f"{name}_TACH", "+3V3", (hu + 5.08, hv - (6.0 if name == "SYS_FAN2" else -5.5)), 90)

    # ---- the BIOS flash ---------------------------------------------------------------------------------
    put("U4", "Memory_Flash:W25Q128JVS", "W25Q128JVSIQ", SOIC8,
        {"4": "GND", "8": "+3V3", "1": "SPI_CS0", "3": "SPI_WP", "7": "SPI_HOLD"})
    passive("C305", "C", "100n", "+3V3", "GND", (177.0, 50.5), 0)
    for i, net in enumerate(("SPI_CS0", "SPI_WP", "SPI_HOLD")):
        passive(f"R{330 + i}", "R", "10k", net, "+3V3", (173.0 + 2.0 * i, 41.0), 90)

    # ARGB_DIN floats while the controller resets: 100k holds the buffer's input low.
    passive("R362", "R", "100k", "ARGB_DIN", "GND", (178.5, 20.5), 0)

    # ---- the standby rail: 3.3 V from the 24-pin's +5VSB, alive whenever the supply is plugged in ---------
    put("U6", "Regulator_Linear:AP2112K-3.3", "AP2112K-3.3", SOT23_5,
        {"1": "+5VSB", "2": "GND", "3": "+5VSB", "5": "+3V3SB"})
    passive("C308", "C", "1u", "+5VSB", "GND", (222.5, 22.0), 90)
    passive("C309", "C", "1u", "+3V3SB", "GND", (229.5, 22.0), 90)

    # ---- buttons, the front panel and its LEDs -------------------------------------------------------
    # Each button and the front panel's switch pull their line to ground; 10k to the standby rail
    # holds it high, so the power button works with the board off.
    put("SW1", "Switch:SW_Push", "POWER", BUTTON, {"1": "PWR_BTN", "2": "GND"})
    put("SW2", "Switch:SW_Push", "RESET", BUTTON, {"1": "RST_BTN", "2": "GND"})
    passive("R360", "R", "10k", "PWR_BTN", "+3V3SB", (203.0, 13.0), 0)
    passive("R361", "R", "10k", "RST_BTN", "+3V3SB", (217.0, 13.0), 0)
    panel = {"1": "HDD_LED_A", "2": "PWR_LED_A", "4": "GND", "5": "GND", "6": "PWR_BTN", "7": "RST_BTN",
             "8": "GND"}  # fmt: skip  # Intel's front panel I/O; 3, the drive LED's cathode, waits for the processor's line; 9 reserved, 10 the key
    put("J32", "Connector_Generic:Conn_02x05_Odd_Even", "F_PANEL", H2x5, panel)
    passive("R340", "R", "330", "+5V", "HDD_LED_A", (196.0, 234.0), 0)
    passive("R341", "R", "330", "+5V", "PWR_LED_A", (199.5, 234.0), 0)

    # ---- USB headers, TPM -----------------------------------------------------------------------------
    usb2 = {"1": "+5V", "2": "+5V", "7": "GND", "8": "GND"}  # 3 to 6 the 2 ports' data, from the processor later
    put("J33", "Connector_Generic:Conn_02x05_Odd_Even", "USB2_HDR", H2x5, usb2)
    usb3 = {"1": "+5V", "19": "+5V", "4": "GND", "7": "GND", "13": "GND", "16": "GND"}
    put("J24", "Connector_Generic:Conn_02x10_Odd_Even", "USB3_HDR", H2x10, usb3)
    tpm = {"4": "+3V3", "7": "GND", "11": "GND"}  # an SPI TPM module's header; its signals come later
    put("J35", "Connector_Generic:Conn_02x07_Odd_Even", "TPM", H2x7, tpm)

    # ---- SATA: the 4 ports' grounds now; their pairs come from the processor's lanes later ------------------
    for i in range(4):
        put(f"J{36 + i}", "Basalt:SATA_7P", f"SATA{i}", "Basalt:SATA_7P_RA_SMT",
            {"S1": "GND", "S4": "GND", "S7": "GND", "MP": "GND"})

    # ---- the CMOS battery ------------------------------------------------------------------------------
    put("BT1", "Device:Battery_Cell", "CR2032", CR2032, {"1": "VBAT_CELL", "2": "GND"})
    put("D5", "Diode:BAT54C", "BAT54C", SOT23, {"1": "VBAT_CELL_R", "2": "+3V3", "3": "VBAT"}, (178.0, 206.5))
    passive("R350", "R", "1k", "VBAT_CELL", "VBAT_CELL_R", (178.0, 210.5), 0)
    passive("C306", "C", "1u", "VBAT", "GND", (181.5, 206.5), 90)
    passive("R351", "R", "20k", "VBAT", "RTC_RST", (178.0, 214.5), 0)
    passive("C307", "C", "1u", "RTC_RST", "GND", (181.5, 214.5), 90)
    put("J31", "Connector_Generic:Conn_01x02", "CLR_CMOS", H1x2, {"1": "RTC_RST", "2": "GND"})

    supplies(d, at, mine)
    nets = {n for p in d.parts if p.ref in mine for n in p.nets.values()}
    return nets - {"GND", "+3V3", "+5V", "+12V"}


def obstacles(d, layer: str, box):
    """The grid of one layer with every copper item the design holds there, each its net's own; "In"
    stands for every inner layer at once."""
    import gridroute  # noqa: PLC0415

    g = gridroute.Grid(box)
    for p in d.pad_boxes():
        if not (p.layer == layer or (layer == "In" and p.layer.startswith("In"))):
            continue
        if p.shape == "circle":
            g.block_disc((p.x1 + p.x2) / 2, (p.y1 + p.y2) / 2, (p.x2 - p.x1) / 2, p.net or None)
        else:
            g.block_rect(p.x1, p.y1, p.x2, p.y2, p.net or None)
    for net, (x, y), size, _drill in d.vias:
        g.block_disc(x, y, size / 2, net)
    for net, a, b, w, lay in d.segments:
        if lay == layer or (layer == "In" and lay.startswith("In")):
            g.block_segment(a, b, w, net)
    x0, y0, x1, y1 = d.outline
    e = d.edge_clearance + gridroute.W / 2 + gridroute.STRAY
    for i in range(g.nx):
        for j in range(g.ny):
            x, y = g.xy(i, j)
            if x < x0 + e or x > x1 - e or y < y0 + e or y > y1 - e:
                g.owner[j * g.nx + i] = 1
    return g


def route(d, at, nets: set[str]) -> list[str]:
    """The ports' own nets, joined by the grid router (gridroute.py) on F.Cu and B.Cu: each net's pads
    in the order of a shortest spanning tree, each link the shortest path that may change layer
    through a via where both layers are free. Returns the links it could not join."""
    import gridroute  # noqa: PLC0415

    box = (*at(166.0, 0.4), *at(243.4, 243.4))
    layers = ("F.Cu", "B.Cu")
    grids = [obstacles(d, lay, box) for lay in layers]
    inner = obstacles(d, "In", box)  # a via passes every inner layer: their copper too
    pads: dict[str, list] = {}
    for b in d.pad_boxes():
        if b.layer == "F.Cu" and b.net and b.net.lstrip("/") in nets:
            pads.setdefault(b.net, []).append(b)
    failed = []
    # Every fine-pitch pin's escape first, so no link routed earlier walls in another's escape end.
    starts = {net: [(*_escape(d, grids[0], net, b), b) for b in items] for net, items in pads.items()}
    for net, items in sorted(pads.items(), key=lambda kv: (kv[0].lstrip("/") not in FIRST, _span(kv[1]))):
        name = net.lstrip("/")
        pts = starts[net]
        done, rest = [pts[0]], pts[1:]
        while rest:
            a, z = min(((p, q) for p in rest for q in done), key=lambda pq: math.dist(pq[0][:2], pq[1][:2]))
            rest.remove(a)
            done.append(a)
            if math.dist(a[:2], z[:2]) < 1e-6:
                continue
            ends = [(0,) if p[2].kind == "smd" else (0, 1) for p in (a, z)]
            found = gridroute.route2(grids, net, a[:2], z[:2], *ends, limit=4_000_000, via_grids=[inner])
            if found is None:
                failed.append(f"{name}: {a[2].ref}.{a[2].number} to {z[2].ref}.{z[2].number}")
                continue
            runs, vias = found
            # The grid's path runs on cell centres; it starts and ends on the exact points, so it meets
            # an escape's end and not only a pad's copper.
            runs[0] = (runs[0][0], [_exact(a[:2])] + runs[0][1])
            runs[-1] = (runs[-1][0], runs[-1][1] + [_exact(z[:2])])
            for lay, run in runs:
                run = [q for k, q in enumerate(run) if k == 0 or math.dist(q, run[k - 1]) > 1e-6]
                d.track(name, run, layers[lay], gridroute.W)
                grids[lay].claim(net, run)
            for v in vias:
                own = d.pcb_net_name(name)
                if any(n == own and math.dist(v, xy) < 0.7 for n, xy, _s, _d in d.vias):
                    continue  # another link of the net changed layer here already
                d.via(name, *v, 0.4, 0.2)
                for g in (*grids, inner):
                    g.block_disc(*v, 0.2, net)
    return failed


def _exact(p) -> tuple[float, float]:
    return round(p[0], 4), round(p[1], 4)


def _span(items) -> float:
    xs = [b.x1 for b in items] + [b.x2 for b in items]
    ys = [b.y1 for b in items] + [b.y2 for b in items]
    return max(xs) - min(xs) + max(ys) - min(ys)


# Routed before the rest, shortest first: the 2 lines to the bottom edge's fan leave the fan controller
# between their neighbours' and are walled in when they come last.
FIRST = ("SYS_FAN2_PWM", "SYS_FAN2_TACH")
FINE = ("U2", "U3")  # the fine-pitch parts: each pin leaves straight out before the grid takes it


def _escape(d, grid, net: str, b) -> tuple[float, float]:
    """Where the grid router starts at a pad: its centre, or for a fine-pitch part's pin the end of a
    straight stub past the pad's outer end, away from the part's centre (0.6 mm for an odd pin, 1.6 for
    an even one), drawn here."""
    cx, cy = (b.x1 + b.x2) / 2, (b.y1 + b.y2) / 2
    if b.ref not in FINE or b.kind != "smd":
        return cx, cy
    px, py = next(p for p in d.parts if p.ref == b.ref).pcb_at
    ox, oy = cx - px, cy - py
    if abs(ox) < 1e-6 and abs(oy) < 1e-6:
        return cx, cy  # the thermal pad
    reach = 0.6 if int(b.number) % 2 else 1.6  # staggered, so 2 neighbours' vias are not side by side
    if abs(ox) >= abs(oy):
        end = (round(cx + math.copysign((b.x2 - b.x1) / 2 + reach, ox), 3), round(cy, 3))
    else:
        end = (round(cx, 3), round(cy + math.copysign((b.y2 - b.y1) / 2 + reach, oy), 3))
    d.track(net.lstrip("/"), [(round(cx, 4), round(cy, 4)), end], "F.Cu", 0.1)
    grid.claim(net, [(cx, cy), end])
    return end


def tap(d, ref: str, number: str, net: str, gaps=(0.25, 0.45, 0.7, 1.0)) -> tuple[float, float] | None:
    """A surface pad of a supply to its plane: a via just past the pad, on the side away from its
    part's centre first, and a track from the pad's centre to it. None for a pad with a through-hole
    twin (a thermal pad's own vias join it)."""
    everything = d.pad_boxes()
    mine = [b for b in everything if b.ref == ref and b.number == number]
    if not mine or any(b.kind != "smd" for b in mine):
        return None
    b = mine[0]
    cx, cy = (b.x1 + b.x2) / 2, (b.y1 + b.y2) / 2
    px, py = next(p for p in d.parts if p.ref == ref).pcb_at
    ox, oy = cx - px, cy - py
    if abs(ox) < 1e-6 and abs(oy) < 1e-6:
        out = (0.0, 1.0)
    elif abs(ox) >= abs(oy):
        out = (math.copysign(1.0, ox), 0.0)
    else:
        out = (0.0, math.copysign(1.0, oy))
    r, drill = 0.2, 0.2
    for gap in gaps:
        for dx, dy in (out, (out[1], out[0]), (-out[1], -out[0]), (-out[0], -out[1])):
            vx = round(cx + dx * ((b.x2 - b.x1) / 2 + gap + r), 3)
            vy = round(cy + dy * ((b.y2 - b.y1) / 2 + gap + r), 3)
            if d._via_fits(vx, vy, r, drill, d.pcb_net_name(net), everything):
                d.via(net, vx, vy, 0.4, drill)
                d.track(net, [(round(cx, 4), round(cy, 4)), (vx, vy)], "F.Cu", 0.25)
                return vx, vy
    raise ValueError(f"{ref}.{number}: no room for a via to {net}")


def supplies(d, at, mine: list[str]) -> None:
    """The +5V spine and stubs on In6, and a via for each surface supply pin."""
    # +5V: from the 24-pin's pin 23 along In6 down the right side and along the bottom to the USB 2.0
    # header's 2 supply pins; stubs to the USB 3 header's 2.
    d.track("+5V", [at(233.5, 87.0), at(SPINE_U, 87.0), at(SPINE_U, FOOT_V), at(176.0, FOOT_V), at(176.0, 240.0)],
            "In6.Cu", 0.6)
    for v in (104.0, 122.0):
        d.track("+5V", [at(SPINE_U, v), at(224.0, v)], "In6.Cu", 0.6)
    # The ARGB header's pin 1 from the run along the top edge (supply.py, v = 13).
    d.track("+5V", [at(174.0, 13.0), at(174.0, 7.0)], "In6.Cu", 0.6)
    # Surface +5V pins: a via each, and In6 to the nearer run.
    _, top = at(0.0, 13.0)
    _, foot = at(0.0, FOOT_V)
    for ref, pad in (("U5", "5"), ("C303", "1"), ("R340", "1"), ("R341", "1")):
        vx, vy = tap(d, ref, pad, "+5V")
        d.track("+5V", [(vx, vy), (vx, top if abs(vy - top) < abs(vy - foot) else foot)], "In6.Cu", 0.4)
    # Every other surface supply pin to its plane.
    for p in list(d.parts):
        if p.ref not in mine:
            continue
        for number, net in p.nets.items():
            if net in ("GND", "+3V3") and not (p.ref in ("U5", "C303") and net == "+5V"):
                tap(d, p.ref, number, net)
