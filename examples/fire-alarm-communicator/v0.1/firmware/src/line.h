/* The captured phone line: when the panel's dialer is off hook.
 *
 * Q3 and Q4 feed TIP from VIN through R18 (27 ohm), which limits the loop to 0.55-0.75 V / 27 ohm,
 * 20 to 28 mA. RING returns to GND through R22 (47 ohm); R23 and C24 bring that voltage to GPIO5.
 * sim/loop_offhook.cir reads 0.78 V at least with 16.5 mA (the limit less 25 %), and
 * sim/loop_onhook.cir 0.04 V at most with the 0.5 mA a panel's line monitor may draw.
 */
#ifndef HERALD_LINE_H
#define HERALD_LINE_H

#include <stdint.h>

#define LINE_OFFHOOK_MV 400u /* above: the dialer draws loop current */

/* The hook changes only after LINE_STABLE readings in a row agree (1 ms apart): a dialer that
 * pulses its hook to flash, or the line's own ringing at seizure, does not count as a call. */
#define LINE_STABLE 20u

typedef struct {
    int offhook; /* 1 while the dialer holds the line */
    int candidate;
    uint8_t count;
} line_t;

void line_init(line_t *l);
/* Feeds 1 reading of GPIO5 in mV; returns 1 when the hook changed. */
int line_feed(line_t *l, uint16_t mv);

#endif
