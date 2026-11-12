"""The Lantronix Open-Q 845 uSOM: its 3 board-to-board connectors and where they sit.

Every pin name is the one in the SOM's hardware datasheet, "Open-Q 845 uSOM Hardware Datasheet",
PDS-0007 Rev C (April 2022), Tables 2, 3 and 4 (JT1, JT2, JT3), read on 2026-11-11 from
https://cdn.lantronix.com/wp-content/uploads/pdf/PDS-0007c-Open-Q-845-uSOM-HW-Datasheet.pdf
The positions are its Figure 7 (land pattern, seen through the top of the SOM): each connector's
centre from the SOM's lower left corner, in mm, y up. The datasheet names the SOM schematic as the
controlling document where the two differ; that schematic needs a development-kit registration.
"""

from __future__ import annotations

SIZE = (50.0, 25.0)  # the SOM's outline, mm (Figure 6)
PCB_THICKNESS = 1.06  # the SOM's own board (Figure 6)
TOP_HEIGHT = 1.32  # its tallest part on top, the Wi-Fi shield (section 6.2)
BOTTOM_HEIGHT = 1.14  # its tallest part underneath, the connectors (section 6.2)
STACK = 3.0  # the gap between the 2 boards with DF40HC(3.0)-100DS-0.4V receptacles (section 6.3)

# Each connector's centre on the SOM (Figure 7, mm from the lower left corner, y up), and the
# corner its pin 1 sits at when seen from above.
CENTRES = {"JT1": (13.9, 2.17), "JT2": (36.9, 2.17), "JT3": (21.2, 22.9)}
PIN1_CORNER = {"JT1": "upper right", "JT2": "upper right", "JT3": "lower left"}

PINS: dict[str, dict[int, str]] = {
    "JT1": {
        1: "GND", 2: "GND", 3: "MIPI_CSI1_CLK_P", 4: "MIPI_CSI3_CLK_P", 5: "MIPI_CSI1_CLK_N", 6: "MIPI_CSI3_CLK_N",
        7: "GND", 8: "GND", 9: "MIPI_CSI1_LANE0_P", 10: "MIPI_CSI3_LANE0_N", 11: "MIPI_CSI1_LANE0_N",
        12: "MIPI_CSI3_LANE0_P", 13: "GND", 14: "GND", 15: "MIPI_CSI1_LANE1_P", 16: "MIPI_CSI3_LANE1_P",
        17: "MIPI_CSI1_LANE1_N", 18: "MIPI_CSI3_LANE1_N", 19: "GND", 20: "GND", 21: "MIPI_CSI1_LANE2_P",
        22: "MIPI_CSI0_CLK_N", 23: "MIPI_CSI1_LANE2_N", 24: "MIPI_CSI0_CLK_P", 25: "GND", 26: "GND",
        27: "MIPI_CSI1_LANE3_P", 28: "MIPI_CSI0_LANE0_P", 29: "MIPI_CSI1_LANE3_N", 30: "MIPI_CSI0_LANE0_N",
        31: "GND", 32: "GND", 33: "MIPI_CSI2_LANE3_P", 34: "MIPI_CSI0_LANE1_P", 35: "MIPI_CSI2_LANE3_N",
        36: "MIPI_CSI0_LANE1_N", 37: "GND", 38: "GND", 39: "MIPI_CSI2_LANE2_N", 40: "MIPI_CSI0_LANE2_P",
        41: "MIPI_CSI2_LANE2_P", 42: "MIPI_CSI0_LANE2_N", 43: "GND", 44: "GND", 45: "MIPI_CSI2_LANE1_N",
        46: "MIPI_CSI0_LANE3_N", 47: "MIPI_CSI2_LANE1_P", 48: "MIPI_CSI0_LANE3_P", 49: "GND", 50: "GND",
        51: "MIPI_CSI2_LANE0_P", 52: "GPIO24_CAM_IRQ", 53: "MIPI_CSI2_LANE0_N", 54: "GPIO40_W_DISABLE_N", 55: "GND",
        56: "GPIO23_CAM3_RST_N", 57: "MIPI_CSI2_CLK_N", 58: "GPIO13_CAM_MCLK0", 59: "MIPI_CSI2_CLK_P",
        60: "GPIO14_CAM_MCLK1", 61: "GND", 62: "VOL_UP_N", 63: "GPIO132_USR_BTN", 64: "CBL_PWR_N",
        65: "SSC5_QUP1_3_SPI1_CS0_N", 66: "GPIO18_CCI_I2C_SCL0", 67: "SSC1_QUP0_1_I2C1_SCL",
        68: "GPIO17_CCI_I2C_SDA0", 69: "SSC0_QUP0_0_I2C1_SDA", 70: "GPIO15_CAM_MCLK2", 71: "SSC8_QUP2_0_SPI2_MISO",
        72: "GPIO25_OIS_SYNC", 73: "SSC11_QUP2_3_SPI2_CS_N", 74: "GND", 75: "SSC9_QUP2_1_SPI2_MOSI",
        76: "GPIO16_CAM_MCLK3", 77: "SSC10_QUP2_2_SPI2_CLK", 78: "GPIO20_CCI_I2C_SCL1", 79: "PM_RESIN_VOLDN_N",
        80: "GPIO19_CCI_I2C_SDA1", 81: "GPIO117_ACCEL_INT", 82: "SDC2_DATA3", 83: "GPIO118_GYRO_INT",
        84: "SDC2_DATA2", 85: "GPIO119_MAG_INT_N", 86: "SDC2_DATA1", 87: "GPIO120_ALSP_INT_N", 88: "SDC2_DATA0",
        89: "GPIO144_WLAN_COEX_UART_TXD", 90: "SDC2_CMD", 91: "GPIO145_WLAN_COEX_UART_RXD", 92: "SDC2_CLK",
        93: "GPIO101_WDOG_DISABLE", 94: "VREG_S4A_1P8", 95: "VREG_LVS2A_1P8", 96: "VREG_S4A_1P8",
        97: "VREG_LVS1A_1P8", 98: "VREG_L22A_2P85", 99: "GPIO53_CODEC_INT2_N", 100: "VREG_L28A_3P0",
    },
    "JT2": {
        1: "SOM_SYS_PWR", 2: "GND", 3: "SOM_SYS_PWR", 4: "GND", 5: "SOM_SYS_PWR", 6: "SOM_SYS_PWR", 7: "SOM_SYS_PWR",
        8: "SOM_SYS_PWR", 9: "SOM_SYS_PWR", 10: "SOM_SYS_PWR", 11: "SOM_SYS_PWR", 12: "SOM_SYS_PWR",
        13: "SOM_SYS_PWR", 14: "SOM_SYS_PWR", 15: "SOM_SYS_PWR", 16: "CS_P", 17: "SOM_SYS_PWR", 18: "CS_N",
        19: "SOM_SYS_PWR", 20: "BATT_ID", 21: "SOM_SYS_PWR", 22: "VBATT_CONN_VSENSE_N", 23: "SOM_SYS_PWR",
        24: "VBATT_CONN_VSENSE_P", 25: "USB_VBUS", 26: "AUX_THERM", 27: "USB_VBUS", 28: "BATT_THERM", 29: "USB_VBUS",
        30: "PHONE_ON_N", 31: "USB_VBUS", 32: "GPIO22_FL_STROBE_TRIG", 33: "USB_VBUS", 34: "GPIO8_CAM_ELDO2_EN",
        35: "USB_CC2", 36: "GPIO29_BL0_EN", 37: "USB_CC1", 38: "GPIO9_CAM2_RST_N", 39: "RGB_BLUE",
        40: "PMI8998_LPG_WLED", 41: "RGB_GREEN", 42: "PMI8998_SPKR_AMP_EN2", 43: "RGB_RED", 44: "PMI_CHARGE_STAT",
        45: "GPIO123", 46: "GPIO126_SDC2_CARD_DET_N", 47: "HAPT_OUT_N", 48: "GPIO21_FLASH_FRONT_EN",
        49: "HAPT_OUT_P", 50: "GPIO10_LCD_TE0", 51: "GPIO31_USB_VBUS_EN", 52: "GPIO122_HRM_INT",
        53: "GPIO6_LCD_RST_N", 54: "GPIO32_TS1_RESET_N", 55: "GPIO80_CAM0_RST_N", 56: "GPIO79_CAM_ELDO9_EN",
        57: "GPIO7_LCD1_RST_N", 58: "GPIO124", 59: "GPIO100_BOOTCFG_2", 60: "GND", 61: "GPIO99_TS_RESET_N",
        62: "USB_SBU_P", 63: "GPIO57_FORCE_USB_BOOT", 64: "USB_SBU_N", 65: "GPIO125_TS_INT_N", 66: "GND", 67: "GND",
        68: "GPIO55_QUP10_0_I2C_SDA", 69: "PCIE1_TX_C_P", 70: "GPIO56_QUP10_1_I2C_SCL", 71: "PCIE1_TX_C_N",
        72: "GPIO58_QUA_MI2S_SCK", 73: "GND", 74: "GPIO59_QUA_MI2S_WS", 75: "PCIE1_REFCLK_N",
        76: "GPIO61_QUA_MI2S_DATA1", 77: "PCIE1_REFCLK_P", 78: "GPIO60_QUA_MI2S_DATA0", 79: "GND",
        80: "GPIO62_QUA_MI2S_DATA2", 81: "PCIE1_RX_N", 82: "GPIO63_QUA_MI2S_DATA3", 83: "PCIE1_RX_P",
        84: "GPIO67_CODEC_SPI_CLK", 85: "GND", 86: "GPIO68_CODEC_SPI_CS_N", 87: "GPIO4_QUP9_2_DBG_UART_TX",
        88: "GPIO65_CODEC_SPI_MISO", 89: "GPIO5_QUP9_3_DBG_UART_RX", 90: "GPIO66_CODEC_SPI_MOSI",
        91: "SSC7_QUP1_5_SPI1_CS2_N", 92: "GPIO64_CODEC_RST_N", 93: "SSC2_QUP1_0_SPI1_MISO",
        94: "GPIO54_CODEC_INT1_N", 95: "SSC3_QUP1_1_SPI1_MOSI", 96: "GPIO102_PCIE1_RST_N",
        97: "SSC4_QUP1_2_SPI1_CLK", 98: "GPIO103_PCIE1_CLKREQ_N", 99: "SSC6_QUP1_4_SPI1_CS1_N",
        100: "GPIO104_PCIE1_WAKE_N",
    },
    "JT3": {
        1: "VREG_L13A_2P95", 2: "VREG_L21A_2P95", 3: "LN_BB_CLK2_WCD", 4: "VREG_L21A_2P95", 5: "PM845_CAM_ELDO1_EN",
        6: "VREG_L21A_2P95", 7: "PM845_CAM_ELDO4_EN", 8: "GND", 9: "GPIO11_LCD_TE1", 10: "MIPI_DSI0_LANE3_N",
        11: "GPIO27_CAM_ELDO3_EN", 12: "MIPI_DSI0_LANE3_P", 13: "GPIO87_QUP5_2_LCD_SPI_CLK", 14: "GND",
        15: "GPIO86_QUP5_1_LCD_SPI_MOSI", 16: "MIPI_DSI0_LANE2_N", 17: "VREG_L19A_3P0", 18: "MIPI_DSI0_LANE2_P",
        19: "GPIO85_QUP5_0_LCD_SPI_MISO", 20: "GND", 21: "GPIO88_QUP5_3_LCD_SPI_CS_N", 22: "MIPI_DSI0_CLK_P",
        23: "GND", 24: "MIPI_DSI0_CLK_N", 25: "MIPI_DSI1_CLK_P", 26: "GND", 27: "MIPI_DSI1_CLK_N",
        28: "MIPI_DSI0_LANE1_N", 29: "GND", 30: "MIPI_DSI0_LANE1_P", 31: "MIPI_DSI1_LANE2_N", 32: "GND",
        33: "MIPI_DSI1_LANE2_P", 34: "MIPI_DSI0_LANE0_P", 35: "GND", 36: "MIPI_DSI0_LANE0_N",
        37: "MIPI_DSI1_LANE3_N", 38: "GND", 39: "MIPI_DSI1_LANE3_P", 40: "GPIO41_QUP3_L0_I2C3_SDA", 41: "GND",
        42: "GPIO42_QUP3_L1_I2C3_SCL", 43: "MIPI_DSI1_LANE1_N", 44: "CABC", 45: "MIPI_DSI1_LANE1_P",
        46: "VREG_L19A_3P0", 47: "GND", 48: "PM_VCOIN", 49: "MIPI_DSI1_LANE0_N", 50: "VREG_L14A_1P8",
        51: "MIPI_DSI1_LANE0_P", 52: "VDISP_P_OUT", 53: "GND", 54: "VDISP_M_OUT", 55: "VREG_S3A_1P35",
        56: "VREG_S3A_1P35", 57: "VREG_S3A_1P35", 58: "VREG_S3A_1P35", 59: "GND", 60: "GPIO28_CAM1_RST_N",
        61: "HAPT_PWM_IN", 62: "GPIO72_CODEC_SLIMBUS_DATA1", 63: "GPIO2_QUP0_L2_SPI_CLK",
        64: "GPIO70_CODEC_SLIMBUS_CLK", 65: "GPIO0_QUP0_L0_SPI_MISO", 66: "GPIO71_CODEC_SLIMBUS_DATA0",
        67: "GPIO1_QUP0_L1_SPI_MOSI", 68: "GPIO69_SPARE", 69: "GPIO3_QUP0_L3_SPI_CS_N", 70: "APQ_RESOUT_N",
        71: "GND", 72: "FLASH_LED1", 73: "USB2_SS_RX_N", 74: "FLASH_LED2", 75: "USB2_SS_RX_P", 76: "VREG_WLED",
        77: "GND", 78: "WLED_SINK3", 79: "USB2_HS_D_N", 80: "WLED_SINK1", 81: "USB2_HS_D_P", 82: "WLED_SINK2",
        83: "GND", 84: "GND", 85: "USB2_SS_TX_C_P", 86: "USB3_HS_D_P", 87: "USB2_SS_TX_C_N", 88: "USB3_HS_D_N",
        89: "GND", 90: "GND", 91: "USB3_SS_TX1_C_N", 92: "USB3_SS_RX0_N", 93: "USB3_SS_TX1_C_P", 94: "USB3_SS_RX0_P",
        95: "GND", 96: "GND", 97: "USB3_SS_RX1_P", 98: "USB3_SS_TX0_C_N", 99: "USB3_SS_RX1_N",
        100: "USB3_SS_TX0_C_P",
    },
}
