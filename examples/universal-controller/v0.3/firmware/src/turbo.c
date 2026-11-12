/* Turbo patterns: see turbo.h. Integer milliseconds only, so the host tests and the RP2040 agree. */
#include "turbo.h"

const uint8_t TURBO_RATES[TURBO_RATE_COUNT] = {5, 8, 10, 20}; /* each divides 1000: a whole number of ms */

void turbo_cfg_init(turbo_cfg_t *cfg)
{
    cfg->pattern = TURBO_OFF;
    cfg->rate = 0;
    cfg->burst = 3;
    cfg->gap_ms = 250;
}

void turbo_state_init(turbo_state_t *st)
{
    st->held = false;
    st->since_ms = 0;
}

uint32_t turbo_period_ms(const turbo_cfg_t *cfg)
{
    uint8_t rate = TURBO_RATES[cfg->rate % TURBO_RATE_COUNT];
    uint32_t p = 1000u / rate;
    return p < 2u ? 2u : p;
}

/* Pressed for the first half of each period, `t` ms into the run of presses. */
static bool square(uint32_t t, uint32_t period) { return (t % period) < period / 2u; }

bool turbo_output(const turbo_cfg_t *cfg, turbo_state_t *st, bool held, uint32_t now_ms)
{
    if (!held) {
        st->held = false;
        return false;
    }
    if (!st->held) {
        st->held = true;
        st->since_ms = now_ms;
    }
    uint32_t t = now_ms - st->since_ms; /* unsigned: right across the 32-bit wrap */
    uint32_t period = turbo_period_ms(cfg);
    uint32_t burst = cfg->burst ? cfg->burst : 1u;

    switch (cfg->pattern) {
    case TURBO_RAPID:
        return square(t, period);
    case TURBO_STAGGER:
        /* Released for the first half period, then RAPID's pattern half a period late. */
        return t >= period / 2u && square(t - period / 2u, period);
    case TURBO_BURST:
        return t < burst * period && square(t, period);
    case TURBO_PULSE: {
        uint32_t group = burst * period + cfg->gap_ms;
        uint32_t u = t % group;
        return u < burst * period && square(u, period);
    }
    case TURBO_OFF:
    case TURBO_PATTERNS:
    default:
        return true;
    }
}

void turbo_next_pattern(turbo_cfg_t *cfg)
{
    cfg->pattern = (turbo_pattern_t)((cfg->pattern + 1) % TURBO_PATTERNS);
}

void turbo_next_rate(turbo_cfg_t *cfg) { cfg->rate = (uint8_t)((cfg->rate + 1u) % TURBO_RATE_COUNT); }

const char *turbo_name(turbo_pattern_t p)
{
    switch (p) {
    case TURBO_RAPID:
        return "RAPID";
    case TURBO_STAGGER:
        return "STAGGER";
    case TURBO_BURST:
        return "BURST";
    case TURBO_PULSE:
        return "PULSE";
    case TURBO_OFF:
    case TURBO_PATTERNS:
    default:
        return "OFF";
    }
}
