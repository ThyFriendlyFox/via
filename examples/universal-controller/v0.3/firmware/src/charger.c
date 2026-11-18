/* The BQ25895's boot-time setup: see charger.h for each write's reason. */
#include "charger.h"

const charger_write_t CHARGER_INIT[CHARGER_INIT_WRITES] = {
    /* REG07: EN_TERM 1, STAT_DIS 0, WATCHDOG 00 (off), EN_TIMER 1, CHG_TIMER 10 (12 h), JEITA_ISET 1. */
    {0x07, 0x8D},
    /* REG02: CONV_START 0, CONV_RATE 1, BOOST_FREQ 1, ICO_EN 1, HVDCP_EN 0, MAXC_EN 0, FORCE_DPDM 0,
     * AUTO_DPDM_EN 1. */
    {0x02, 0x71},
    /* REG00: EN_HIZ 0, EN_ILIM 1, IINLIM 63 (3.25 A). */
    {0x00, 0x7F},
    /* REG04: EN_PUMPX 0, ICHG 39 (2.496 A). */
    {0x04, 0x27},
};

uint32_t charger_iinlim_ma(uint8_t reg00) { return 100u + 50u * (reg00 & 0x3Fu); }

uint32_t charger_ichg_ma(uint8_t reg04) { return 64u * (reg04 & 0x7Fu); }
