/* The scroll strip's decoder.
 *
 * The touch tile carries 6 stripes, channels A B C A B C from the fingertip's end, 1.55 mm apart.
 * The radio's touch controller (TSC) counts charge transfers on each channel: a thumb over a
 * stripe adds capacitance and the count falls. Each channel's fall from its untouched count is
 * its signal. A thumb covers several stripes, so the 3 signals rise and fall in turn as it slides,
 * 120 degrees apart: their Clarke angle is the thumb's place within 1 cycle of 3 stripes (4.65 mm).
 * Unwrapped from reading to reading it is a position along the strip, and every quarter cycle
 * (1.16 mm) is 1 scroll detent: up when the thumb moves toward the fingertip.
 */
#ifndef STRIP_H
#define STRIP_H

#include <stdbool.h>
#include <stdint.h>

#define STRIP_CHANNELS 3
#define STRIP_DETENTS_PER_CYCLE 4
/* A touch: the 3 signals' sum reaches STRIP_TOUCH counts; it ends below STRIP_RELEASE. */
#define STRIP_TOUCH 120
#define STRIP_RELEASE 80
/* While untouched, each baseline moves 1/16 of the way to its count each reading. */
#define STRIP_BASE_SHIFT 4

typedef struct {
    int32_t base[STRIP_CHANNELS]; /* untouched counts, in 1/16 counts */
    bool touched;
    float angle;    /* the last Clarke angle, radians */
    float travel;   /* unwrapped travel since the touch began, in cycles; + toward the hand */
    int32_t issued; /* detents reported since the touch began */
} strip_t;

/* Start with the counts of an untouched strip. */
void strip_init(strip_t *s, const uint16_t counts[STRIP_CHANNELS]);

/* Feed 1 reading of the 3 channels. Returns the detents to scroll since the last reading: positive
 * scrolls up (the thumb moved toward the fingertip), 0 when the strip is not touched. */
int strip_update(strip_t *s, const uint16_t counts[STRIP_CHANNELS]);

#endif
