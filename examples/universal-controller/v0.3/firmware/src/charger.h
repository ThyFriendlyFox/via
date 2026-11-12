/* The BQ25895's setup: the register writes the RP2040 makes at boot over I2C0 (address 0x6A).
 *
 * Register fields from TI's BQ25895 datasheet (SLUSC88), section 9.5, "Register Maps".
 *
 * Why each write:
 *   REG00  Input current: 3.25 A asked for, and EN_ILIM on, so R12 (120 ohms, 2.96 A) caps it. The
 *          charger's input current optimizer (ICO, REG02) then finds what the source can give
 *          without its voltage sagging: 3 A from a USB-C charger, less from a console's port.
 *   REG02  HVDCP and MaxCharge off. Both raise VBUS to 9 or 12 V on a charger that offers it, and
 *          VBUS also feeds the auth donor on J2 (through U13), which takes 5 V only. D+ and D- are
 *          not wired to the charger either, so it cannot ask, but the firmware turns both off.
 *          ICO on; the ADC converts continuously, so the screen can show VBUS and the charge current.
 *   REG04  Charge current: 2.5 A (39 x 64 mA = 2.496 A), for a 1S cell of 3000 mAh or more.
 *   REG07  The I2C watchdog off: otherwise, 40 s after the last write the charger goes back to its
 *          defaults, HVDCP included.
 */
#ifndef ROSETTA_CHARGER_H
#define ROSETTA_CHARGER_H

#include <stddef.h>
#include <stdint.h>

#define CHARGER_I2C_ADDR 0x6Au

typedef struct {
    uint8_t reg;
    uint8_t value;
} charger_write_t;

#define CHARGER_INIT_WRITES 4u

/* The setup, in the order to write it: the watchdog first, so nothing reverts while the rest goes in. */
extern const charger_write_t CHARGER_INIT[CHARGER_INIT_WRITES];

/* Fields, for the tests and the screen. */
uint32_t charger_iinlim_ma(uint8_t reg00); /* REG00 IINLIM: 100 mA + 50 mA a step */
uint32_t charger_ichg_ma(uint8_t reg04);   /* REG04 ICHG: 64 mA a step */

#endif
