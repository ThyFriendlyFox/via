/* Turbo: a button that repeats while it is held, in 1 of 4 fixed patterns, set from the 2 back
 * buttons (SW19 TURBO_A, SW20 TURBO_B).
 *
 * Every pattern is a fixed, regular timing: the same press gives the same presses, to the
 * millisecond, every time. Nothing here varies or randomizes the timing.
 *
 *   RAPID    while held: pressed for half a period, released for half, at the button's rate.
 *   STAGGER  RAPID, half a period late: 2 buttons, 1 on RAPID and 1 on STAGGER, alternate.
 *   BURST    1 press of the button: `burst` presses at the rate, then released until it is let go.
 *   PULSE    while held: `burst` presses at the rate, then a gap of `gap_ms`, again and again.
 *
 * The controls: hold TURBO_A and press a button to step that button's pattern
 * (OFF, RAPID, STAGGER, BURST, PULSE, OFF); hold TURBO_B and press a button to step its rate
 * through TURBO_RATES. The screen and the button's stick ring show what each button is set to.
 */
#ifndef ROSETTA_TURBO_H
#define ROSETTA_TURBO_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    TURBO_OFF = 0,
    TURBO_RAPID,
    TURBO_STAGGER,
    TURBO_BURST,
    TURBO_PULSE,
    TURBO_PATTERNS, /* how many there are */
} turbo_pattern_t;

/* The rates a button steps through, in presses per second. 20 a second is a press every 50 ms:
 * every console polls its controller at least every 8 ms, so each press and release is seen. */
#define TURBO_RATE_COUNT 4u
extern const uint8_t TURBO_RATES[TURBO_RATE_COUNT];

typedef struct {
    turbo_pattern_t pattern;
    uint8_t rate;     /* an index into TURBO_RATES */
    uint8_t burst;    /* BURST and PULSE: presses in a group, 1 or more */
    uint16_t gap_ms;  /* PULSE: released time between groups */
} turbo_cfg_t;

typedef struct {
    bool held;          /* the button was held at the last call */
    uint32_t since_ms;  /* when it was pressed */
} turbo_state_t;

void turbo_cfg_init(turbo_cfg_t *cfg);           /* OFF, the first rate, a burst of 3, a gap of 250 ms */
void turbo_state_init(turbo_state_t *st);

/* The length of 1 press and release at the button's rate, in ms (rounded down, never under 2). */
uint32_t turbo_period_ms(const turbo_cfg_t *cfg);

/* Whether the button reads as pressed at `now_ms`, given whether the hand holds it. Call it at least
 * once per report; it remembers when the press began, so its answer depends only on how long the
 * button has been held. A button that is let go reads released at once, in every pattern. */
bool turbo_output(const turbo_cfg_t *cfg, turbo_state_t *st, bool held, uint32_t now_ms);

/* The back buttons' 2 steps. */
void turbo_next_pattern(turbo_cfg_t *cfg);
void turbo_next_rate(turbo_cfg_t *cfg);

/* A short name for the screen: "OFF", "RAPID", "STAGGER", "BURST", "PULSE". */
const char *turbo_name(turbo_pattern_t p);

#endif
