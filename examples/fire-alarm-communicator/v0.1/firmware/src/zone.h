/* The supervised inputs: from the ADC's reading of a loop to what the panel's contact says.
 *
 * Each loop (J3) runs from R32 (4.7k to +3V3) through R31 (100) to the panel's contact, which has a
 * 4.7k end-of-line resistor across it. A closed contact shorts the loop, a whole loop with an open
 * contact reads about half of +3V3, and a cut wire reads +3V3. sim/zone_*.cir hold each reading
 * 200 mV or more from these thresholds at every corner (+3V3 within 3 %, resistors 1 %, the
 * end-of-line resistor 5 %, 0 to 100 ohm of wire, 1 uA of leakage, 0 to 50 C).
 */
#ifndef HERALD_ZONE_H
#define HERALD_ZONE_H

#include <stdint.h>

#define ZONE_SHORT_MAX_MV 600u   /* below: the contact is closed (deck: 0.15 V at most) */
#define ZONE_NORMAL_MIN_MV 1100u /* the end-of-line band (decks: 1.55 to 1.80 V) */
#define ZONE_NORMAL_MAX_MV 2300u
#define ZONE_OPEN_MIN_MV 2700u /* above: the wire is cut (deck: 3.18 V at least) */

typedef enum {
    ZONE_FAULT = 0,  /* between bands: a loop that is neither whole nor shorted nor open */
    ZONE_NORMAL = 1, /* the loop is whole and the contact open */
    ZONE_ACTIVE = 2, /* the contact is closed: the panel reports this zone's condition */
    ZONE_OPEN = 3,   /* a wire is cut: a trouble on this input */
} zone_state_t;

zone_state_t zone_classify(uint16_t mv);

/* A new state is taken only after ZONE_STABLE readings in a row agree: the firmware reads each loop
 * every 10 ms, so a state must hold for 100 ms. A relay's contact bounce or a spike changes nothing. */
#define ZONE_STABLE 10u

typedef struct {
    zone_state_t state;     /* what the zone reports now */
    zone_state_t candidate; /* what the last readings agree on */
    uint8_t count;
} zone_t;

void zone_init(zone_t *z);
/* Feeds 1 reading; returns 1 when the reported state changed. */
int zone_feed(zone_t *z, uint16_t mv);

#endif
