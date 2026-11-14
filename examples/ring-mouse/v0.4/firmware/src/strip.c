#include "strip.h"

#include <math.h>

#define TWO_PI 6.2831853f

void strip_init(strip_t *s, const uint16_t counts[STRIP_CHANNELS])
{
    for (int i = 0; i < STRIP_CHANNELS; i++) {
        s->base[i] = (int32_t)counts[i] << STRIP_BASE_SHIFT;
    }
    s->touched = false;
    s->angle = 0.0f;
    s->travel = 0.0f;
    s->issued = 0;
}

/* The Clarke angle of 3 signals 120 degrees apart: A alone is 0, B alone 120, C alone 240. */
static float clarke(const int32_t d[STRIP_CHANNELS])
{
    float alpha = 2.0f * (float)d[0] - (float)d[1] - (float)d[2];
    float beta = 1.7320508f * ((float)d[1] - (float)d[2]);
    return atan2f(beta, alpha);
}

int strip_update(strip_t *s, const uint16_t counts[STRIP_CHANNELS])
{
    int32_t d[STRIP_CHANNELS];
    int32_t sum = 0;
    for (int i = 0; i < STRIP_CHANNELS; i++) {
        d[i] = (s->base[i] >> STRIP_BASE_SHIFT) - (int32_t)counts[i];
        if (d[i] < 0) {
            d[i] = 0; /* a count above its baseline is drift, not a thumb */
        }
        sum += d[i];
    }

    if (!s->touched) {
        if (sum < STRIP_TOUCH) {
            for (int i = 0; i < STRIP_CHANNELS; i++) {
                int32_t target = (int32_t)counts[i] << STRIP_BASE_SHIFT;
                s->base[i] += (target - s->base[i]) >> STRIP_BASE_SHIFT;
            }
            return 0;
        }
        s->touched = true;
        s->angle = clarke(d);
        s->travel = 0.0f;
        s->issued = 0;
        return 0;
    }

    if (sum < STRIP_RELEASE) {
        s->touched = false;
        return 0;
    }

    float a = clarke(d);
    float step = a - s->angle;
    /* The shorter way round: a thumb moves less than half a cycle between 2 readings. */
    if (step > TWO_PI / 2) {
        step -= TWO_PI;
    } else if (step < -TWO_PI / 2) {
        step += TWO_PI;
    }
    s->angle = a;
    s->travel += step / TWO_PI;

    /* Toward the hand is + travel and scrolls down: detents are the negative of travel. */
    int32_t due = (int32_t)floorf(-s->travel * STRIP_DETENTS_PER_CYCLE + 0.5f);
    int out = (int)(due - s->issued);
    s->issued = due;
    return out;
}
