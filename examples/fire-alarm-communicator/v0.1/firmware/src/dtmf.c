#include "dtmf.h"

#include <math.h>

static const float FREQS[8] = {697.0f, 770.0f, 852.0f, 941.0f, 1209.0f, 1336.0f, 1477.0f, 1633.0f};
static const char KEYS[4][4] = {
    {'1', '2', '3', 'A'},
    {'4', '5', '6', 'B'},
    {'7', '8', '9', 'C'},
    {'*', '0', '#', 'D'},
};

static float goertzel(const int16_t *x, uint16_t n, float f)
{
    const float coeff = 2.0f * cosf(2.0f * 3.14159265f * f / (float)DTMF_RATE);
    float s1 = 0.0f, s2 = 0.0f;
    for (uint16_t i = 0; i < n; i++) {
        float s0 = (float)x[i] + coeff * s1 - s2;
        s2 = s1;
        s1 = s0;
    }
    return s1 * s1 + s2 * s2 - coeff * s1 * s2;
}

/* The index of the largest of 4 powers, and whether it beats the others by DTMF_GROUP_RATIO. */
static int strongest(const float *p, int *clear)
{
    int best = 0;
    for (int i = 1; i < 4; i++)
        if (p[i] > p[best])
            best = i;
    *clear = 1;
    for (int i = 0; i < 4; i++)
        if (i != best && p[best] < DTMF_GROUP_RATIO * p[i])
            *clear = 0;
    return best;
}

char dtmf_window(const int16_t *x, uint16_t n)
{
    float energy = 0.0f, first = 0.0f;
    for (uint16_t i = 0; i < n; i++) {
        energy += (float)x[i] * (float)x[i];
        if (i == n / 2u - 1u)
            first = energy;
    }
    if (energy <= 0.0f || sqrtf(energy / (float)n) < DTMF_MIN_RMS)
        return 0;
    if (first < DTMF_HALF_SHARE * energy || energy - first < DTMF_HALF_SHARE * energy)
        return 0;
    /* A sine of amplitude a gives a Goertzel power of (n a / 2)^2 and an energy of n a^2 / 2: the
     * power over (n / 2) x energy is the share of the window's energy at that frequency. */
    float share[8];
    for (int k = 0; k < 8; k++)
        share[k] = goertzel(x, n, FREQS[k]) / (0.5f * (float)n * energy);
    int row_clear, col_clear;
    int row = strongest(share, &row_clear);
    int col = strongest(share + 4, &col_clear);
    if (!row_clear || !col_clear)
        return 0;
    if (share[row] + share[4 + col] < DTMF_PAIR_SHARE)
        return 0;
    float twist = 10.0f * log10f(share[4 + col] / share[row]); /* the column over the row, dB */
    if (twist > DTMF_TWIST_FWD_DB || twist < -DTMF_TWIST_REV_DB)
        return 0;
    return KEYS[row][col];
}

void dtmf_init(dtmf_t *d)
{
    d->head = 0;
    d->filled = 0;
    d->since = 0;
    d->last = 0;
    d->agree = 0;
    d->reported = 0;
}

char dtmf_feed(dtmf_t *d, int16_t sample)
{
    d->ring[d->head] = sample;
    d->head = (uint16_t)((d->head + 1u) % DTMF_N);
    if (d->filled < DTMF_N)
        d->filled++;
    if (++d->since < DTMF_HOP || d->filled < DTMF_N)
        return 0;
    d->since = 0;
    int16_t window[DTMF_N];
    for (uint16_t i = 0; i < DTMF_N; i++)
        window[i] = d->ring[(d->head + i) % DTMF_N];
    char key = dtmf_window(window, DTMF_N);
    if (key == 0) {
        d->last = 0;
        d->agree = 0;
        d->reported = 0;
        return 0;
    }
    if (key != d->last) {
        d->last = key;
        d->agree = 1;
        d->reported = 0;
        return 0;
    }
    if (d->agree < 255)
        d->agree++;
    if (d->agree >= 2 && !d->reported) {
        d->reported = 1;
        return key;
    }
    return 0;
}
