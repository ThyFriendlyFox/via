/* Host tests for the charger's setup: each write's fields, read back as the datasheet lays them out. */
#include <stdio.h>

#include "charger.h"

static int failures;

#define CHECK(cond)                                                                \
    do {                                                                           \
        if (!(cond)) {                                                             \
            fprintf(stderr, "%s:%d: CHECK(%s) failed\n", __FILE__, __LINE__, #cond); \
            failures++;                                                            \
        }                                                                          \
    } while (0)

static int value_of(uint8_t reg)
{
    for (unsigned i = 0; i < CHARGER_INIT_WRITES; i++) {
        if (CHARGER_INIT[i].reg == reg) {
            return CHARGER_INIT[i].value;
        }
    }
    return -1;
}

#define BIT(v, n) (((v) >> (n)) & 1)

int main(void)
{
    /* The watchdog goes off first: a write after it cannot be undone by a timeout. */
    CHECK(CHARGER_INIT[0].reg == 0x07);
    int r07 = value_of(0x07);
    CHECK(((r07 >> 4) & 3) == 0); /* WATCHDOG 00: off */
    CHECK(BIT(r07, 7) == 1);      /* termination stays on */
    CHECK(BIT(r07, 3) == 1);      /* the safety timer stays on */

    int r02 = value_of(0x02);
    CHECK(BIT(r02, 3) == 0); /* HVDCP_EN: VBUS stays 5 V */
    CHECK(BIT(r02, 2) == 0); /* MAXC_EN */
    CHECK(BIT(r02, 4) == 1); /* ICO_EN */
    CHECK(BIT(r02, 1) == 0); /* no forced D+/D- detection */

    int r00 = value_of(0x00);
    CHECK(BIT(r00, 7) == 0); /* not high-impedance: the charger draws from VBUS */
    CHECK(BIT(r00, 6) == 1); /* EN_ILIM: R12 caps the input */
    CHECK(charger_iinlim_ma((uint8_t)r00) == 3250);

    int r04 = value_of(0x04);
    CHECK(BIT(r04, 7) == 0); /* no pump-express */
    CHECK(charger_ichg_ma((uint8_t)r04) == 2496);
    /* 2.5 A of charge at 4.2 V is 10.5 W, under the 15 W a 5 V, 3 A source gives. */
    CHECK(charger_ichg_ma((uint8_t)r04) * 42u < 5u * 2960u * 10u);

    if (failures) {
        fprintf(stderr, "charger: %d check(s) failed\n", failures);
        return 1;
    }
    puts("charger: every check passed");
    return 0;
}
