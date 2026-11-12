#include "zone.h"

zone_state_t zone_classify(uint16_t mv)
{
    if (mv < ZONE_SHORT_MAX_MV)
        return ZONE_ACTIVE;
    if (mv >= ZONE_NORMAL_MIN_MV && mv <= ZONE_NORMAL_MAX_MV)
        return ZONE_NORMAL;
    if (mv > ZONE_OPEN_MIN_MV)
        return ZONE_OPEN;
    return ZONE_FAULT;
}

void zone_init(zone_t *z)
{
    /* A loop is taken as normal at power-up until ZONE_STABLE readings say otherwise. */
    z->state = ZONE_NORMAL;
    z->candidate = ZONE_NORMAL;
    z->count = 0;
}

int zone_feed(zone_t *z, uint16_t mv)
{
    zone_state_t s = zone_classify(mv);
    if (s != z->candidate) {
        z->candidate = s;
        z->count = 1;
    } else if (z->count < ZONE_STABLE) {
        z->count++;
    }
    if (z->count >= ZONE_STABLE && z->candidate != z->state) {
        z->state = z->candidate;
        return 1;
    }
    return 0;
}
