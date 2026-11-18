/* Lark v0.1: the light's rules (light.h). */
#include "light.h"

#include <math.h>

lark_mode lark_mode_from_hall(int a_low, int b_low)
{
    if (a_low && !b_low) {
        return LARK_MODE_ALEXA;
    }
    if (b_low && !a_low) {
        return LARK_MODE_APPLE;
    }
    return LARK_MODE_VOICE;
}

static unsigned clamp_min(unsigned share)
{
    if (share == 0u || share >= LARK_SHARE_MIN) {
        return share;
    }
    return share * 2u >= LARK_SHARE_MIN ? LARK_SHARE_MIN : 0u;
}

void lark_mix(unsigned level, unsigned cct_k, unsigned budget, unsigned *warm, unsigned *cool)
{
    if (level > 1000u) {
        level = 1000u;
    }
    if (budget > LARK_BUDGET) {
        budget = LARK_BUDGET;
    }
    if (cct_k < LARK_CCT_WARM) {
        cct_k = LARK_CCT_WARM;
    }
    if (cct_k > LARK_CCT_COOL) {
        cct_k = LARK_CCT_COOL;
    }
    /* The cool string's part of the light on the mired scale, where equal steps look equal. */
    double mw = 1e6 / LARK_CCT_WARM, mc = 1e6 / LARK_CCT_COOL, m = 1e6 / cct_k;
    double f = (mw - m) / (mw - mc);
    unsigned total = (unsigned)((double)budget * level / 1000.0 + 0.5);
    unsigned c = (unsigned)(total * f + 0.5);
    unsigned w = total - c;
    w = clamp_min(w);
    c = clamp_min(c);
    /* Rounding a share up to the minimum must not take the pair over the budget. */
    while (w + c > budget) {
        if (w >= c && w > 0u) {
            w = w > LARK_SHARE_MIN ? w - 1u : 0u;
        } else {
            c = c > LARK_SHARE_MIN ? c - 1u : 0u;
        }
    }
    *warm = w;
    *cool = c;
}

unsigned lark_vbus_v(unsigned sense_mv)
{
    /* VBUS = V(sense) x (2000k + 24.9k) / 24.9k */
    return (unsigned)(sense_mv * (2024.9 / 24.9) / 1000.0 + 0.5);
}

unsigned lark_foldback_line(unsigned budget, unsigned vbus_valley_v)
{
    if (vbus_valley_v >= 110u) {
        return budget;
    }
    if (vbus_valley_v <= 103u) {
        return budget / 2u;
    }
    return budget / 2u + budget / 2u * (vbus_valley_v - 103u) / 7u;
}

int lark_disc_temp_dc(unsigned ntc_mv)
{
    if (ntc_mv == 0u || ntc_mv >= 3300u) {
        return ntc_mv == 0u ? 2000 : -400; /* a shorted NTC reads hot, an open one cold */
    }
    double r = 10000.0 * ntc_mv / (3300.0 - ntc_mv);
    double t = 1.0 / (1.0 / 298.15 + log(r / 100000.0) / 4250.0) - 273.15;
    return (int)lround(t * 10.0);
}

unsigned lark_foldback_temp(unsigned budget, int disc_dc)
{
    if (disc_dc > 1100) {
        return 0u;
    }
    if (disc_dc <= 850) {
        return budget;
    }
    if (disc_dc >= 1050) {
        return budget / 5u;
    }
    /* From the whole at 85 C to a fifth at 105 C: 4 % of it per degree. */
    return budget - budget * 4u * (unsigned)(disc_dc - 850) / 1000u;
}
