/* The mode knob: from the MCP3208's reading of the wiper to the console the controller speaks to.
 *
 * SW1 taps a 6-resistor ladder, so position k reads (6 - k) / 6 of full scale. The ADC's reference
 * is the ladder's own rail, so the reading is a ratio and the rail's tolerance drops out. Between
 * detents the wiper touches no tap and R46 pulls it to ~0. sim/mode_*.cir prove each position
 * stays within 0.04 of full scale of its nominal at every corner, and the gap reads under 0.042.
 */
#ifndef ROSETTA_MODE_H
#define ROSETTA_MODE_H

#include <stdbool.h>
#include <stdint.h>

#define MODE_ADC_FULL 4096u /* the MCP3208 is 12 bits */

typedef enum {
    MODE_NONE = 0, /* between detents, or a reading no position owns */
    MODE_PS4 = 1,
    MODE_PS5 = 2,
    MODE_XBOX = 3,
    MODE_SWITCH = 4,
    MODE_BLUETOOTH = 5,
} mode_t_;

typedef enum { LINK_USB, LINK_BLUETOOTH } link_t;

/* What each mode is on the wire. A USB mode enumerates with the console's own controller's IDs;
 * PS4, PS5 and Xbox also need the auth donor on J2 to answer the console's challenge. */
typedef struct {
    const char *name;
    link_t link;
    uint16_t vid, pid; /* 0 for Bluetooth */
    bool needs_auth;   /* the console checks a signature only a licensed controller makes */
    uint32_t rgb;      /* the light ring's colour, 0xRRGGBB */
} mode_info_t;

const mode_info_t *mode_info(mode_t_ m);

/* 1 reading to a position: the nearest tap, if the reading lies within the guard band of it;
 * MODE_NONE below the lowest threshold (the gap between detents) or outside every band. */
mode_t_ mode_decode(uint16_t code);

/* The knob's state across readings. A new position is taken only after `MODE_STABLE` readings in a
 * row agree, so the wiper sweeping across taps on its way to a detent changes nothing. */
#define MODE_STABLE 8u

typedef enum {
    STEP_NONE,     /* nothing to do */
    STEP_DETACH,   /* the knob left the current mode: drop off the bus, lights off */
    STEP_ATTACH,   /* the knob settled on a new mode: come back as that mode's device */
} step_t;

typedef struct {
    mode_t_ active;    /* the mode the controller speaks now (MODE_NONE while detached) */
    mode_t_ candidate; /* the position the last readings agree on */
    uint8_t count;     /* how many readings in a row agree on it */
} knob_t;

void knob_init(knob_t *k);
step_t knob_feed(knob_t *k, uint16_t code);

#endif
