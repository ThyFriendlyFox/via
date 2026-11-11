#include "mode.h"

#include <stddef.h>

/* Thresholds sit halfway between neighbours: 1/12 of full scale from each nominal. A reading
 * counts for a position only inside a band narrower than that by GUARD, so noise on a reading
 * near a threshold gives MODE_NONE, never the neighbour. The decks hold every corner within 0.04
 * of full scale (164 counts) of nominal; the band is 341 - 64 = 277 counts. */
#define HALF (MODE_ADC_FULL / 12u) /* 341: the distance to a threshold */
#define GUARD 64u

static const mode_info_t INFO[] = {
    [MODE_NONE] = {"none", LINK_USB, 0, 0, false, 0x000000},
    [MODE_PS4] = {"PS4", LINK_USB, 0x054C, 0x09CC, true, 0x0050EF},
    [MODE_PS5] = {"PS5", LINK_USB, 0x054C, 0x0CE6, true, 0xE8ECFF},
    [MODE_XBOX] = {"Xbox", LINK_USB, 0x045E, 0x02EA, true, 0x16C60C},
    [MODE_SWITCH] = {"Switch", LINK_USB, 0x057E, 0x2009, false, 0xE60012},
    [MODE_BLUETOOTH] = {"Bluetooth", LINK_BLUETOOTH, 0, 0, false, 0x00A0FF},
};

const mode_info_t *mode_info(mode_t_ m)
{
    if ((unsigned)m > MODE_BLUETOOTH) {
        return NULL;
    }
    return &INFO[m];
}

static uint16_t nominal(unsigned k)
{
    /* position k at (6 - k) / 6 of full scale, rounded */
    return (uint16_t)(((6u - k) * MODE_ADC_FULL + 3u) / 6u);
}

mode_t_ mode_decode(uint16_t code)
{
    if (code >= MODE_ADC_FULL) {
        return MODE_NONE; /* no 12-bit reading is this large: a bus fault */
    }
    if (code < HALF) {
        return MODE_NONE; /* the gap between detents */
    }
    for (unsigned k = 1; k <= 5; k++) {
        uint16_t n = nominal(k);
        uint16_t d = code > n ? code - n : n - code;
        if (d <= HALF - GUARD) {
            return (mode_t_)k;
        }
    }
    return MODE_NONE;
}

void knob_init(knob_t *k)
{
    k->active = MODE_NONE;
    k->candidate = MODE_NONE;
    k->count = 0;
}

step_t knob_feed(knob_t *k, uint16_t code)
{
    mode_t_ m = mode_decode(code);
    if (m == k->candidate) {
        if (k->count < MODE_STABLE) {
            k->count++;
        }
    } else {
        k->candidate = m;
        k->count = 1;
    }
    if (k->count < MODE_STABLE || k->candidate == k->active) {
        return STEP_NONE;
    }
    /* The knob settled somewhere new. Leaving a mode always detaches first, so a console never
     * sees one device turn into another without a disconnect. */
    if (k->active != MODE_NONE) {
        k->active = MODE_NONE;
        return STEP_DETACH;
    }
    k->active = k->candidate;
    return k->active == MODE_NONE ? STEP_NONE : STEP_ATTACH;
}
