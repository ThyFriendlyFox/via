#include "air.h"

#include <math.h>

void air_init(air_t *a)
{
    a->residue_x = 0.0f;
    a->residue_y = 0.0f;
}

void air_to_ring(const float chip[3], float ring[3])
{
    float tx = AIR_CHIP_X * chip[0], ty = AIR_CHIP_Y * chip[1], tz = AIR_CHIP_Z * chip[2];
    /* The tile's x and z, seen along the finger, are the ring's turned by the tile's angle. */
    float c = cosf(AIR_TILE_DEG * 3.14159265f / 180.0f), s = sinf(AIR_TILE_DEG * 3.14159265f / 180.0f);
    ring[0] = c * tx + s * tz;
    ring[1] = ty;
    ring[2] = -s * tx + c * tz;
}

static float deadband(float rate)
{
    if (fabsf(rate) < AIR_DEADBAND) {
        return 0.0f;
    }
    return rate > 0 ? rate - AIR_DEADBAND : rate + AIR_DEADBAND;
}

static int whole(float *residue)
{
    float n = truncf(*residue);
    *residue -= n;
    return (int)n;
}

void air_update(air_t *a, const float gyro_dps[3], bool touched, float dt, int *dx, int *dy)
{
    *dx = 0;
    *dy = 0;
    if (!touched) {
        air_init(a); /* the clutch is open: nothing carries over to the next touch */
        return;
    }
    float r[3];
    air_to_ring(gyro_dps, r);
    /* Turning left is + about z (up), and moves the cursor left; pointing up is + about x and
     * moves it up, which on a screen is - y. */
    a->residue_x += -deadband(r[2]) * AIR_GAIN * dt;
    a->residue_y += -deadband(r[0]) * AIR_GAIN * dt;
    *dx = whole(&a->residue_x);
    *dy = whole(&a->residue_y);
}
