/* Host tests for the knob decoder: cc -std=c11 -Wall -Wextra -Werror -I../src (make test). */
#include <stdio.h>
#include <stdlib.h>

#include "mode.h"

static int failures;

#define CHECK(cond)                                                                \
    do {                                                                           \
        if (!(cond)) {                                                             \
            fprintf(stderr, "%s:%d: CHECK(%s) failed\n", __FILE__, __LINE__, #cond); \
            failures++;                                                            \
        }                                                                          \
    } while (0)

static uint16_t code_of(double ratio) { return (uint16_t)(ratio * MODE_ADC_FULL + 0.5); }

/* Each position's nominal reading, and the ends the decks measured at their corners
 * (sim/mode_p*.cir, `workcenter sim . --deck mode_pK`). */
static void test_positions(void)
{
    const double nominal[] = {0, 5.0 / 6, 4.0 / 6, 3.0 / 6, 2.0 / 6, 1.0 / 6};
    for (int k = 1; k <= 5; k++) {
        CHECK(mode_decode(code_of(nominal[k])) == (mode_t_)k);
        CHECK(mode_decode(code_of(nominal[k] - 0.04)) == (mode_t_)k);
        CHECK(mode_decode(code_of(nominal[k] + 0.04)) == (mode_t_)k);
    }
    CHECK(mode_decode(code_of(0.823811)) == MODE_PS4);
    CHECK(mode_decode(code_of(0.48806)) == MODE_XBOX);
    CHECK(mode_decode(code_of(0.162797)) == MODE_BLUETOOTH);
}

/* Between detents, and every threshold: no position, never the neighbour. */
static void test_gaps(void)
{
    CHECK(mode_decode(0) == MODE_NONE);
    CHECK(mode_decode(code_of(0.0417)) == MODE_NONE);
    for (int k = 1; k <= 4; k++) {
        double threshold = (6.0 - k) / 6 - 1.0 / 12;
        CHECK(mode_decode(code_of(threshold)) == MODE_NONE);
    }
    CHECK(mode_decode(4095) == MODE_NONE);
    CHECK(mode_decode(4096) == MODE_NONE);
}

static void feed(knob_t *k, uint16_t code, unsigned n, step_t *last)
{
    for (unsigned i = 0; i < n; i++) {
        step_t s = knob_feed(k, code);
        if (s != STEP_NONE) {
            *last = s;
        }
    }
}

/* Turning from PS5 to Switch: the wiper crosses Xbox's tap on the way. A short brush past it
 * changes nothing; the controller detaches once and attaches once, as Switch. */
static void test_turn(void)
{
    knob_t k;
    knob_init(&k);
    step_t last = STEP_NONE;
    feed(&k, code_of(4.0 / 6), MODE_STABLE, &last);
    CHECK(k.active == MODE_PS5 && last == STEP_ATTACH);

    last = STEP_NONE;
    feed(&k, 0, 3, &last);                                  /* off the PS5 tap */
    feed(&k, code_of(3.0 / 6), MODE_STABLE - 1, &last);     /* brushing past Xbox */
    CHECK(k.active == MODE_PS5 && last == STEP_NONE);

    feed(&k, 0, MODE_STABLE, &last); /* in the gap long enough: detach */
    CHECK(k.active == MODE_NONE && last == STEP_DETACH);

    last = STEP_NONE;
    feed(&k, code_of(2.0 / 6), MODE_STABLE, &last);
    CHECK(k.active == MODE_SWITCH && last == STEP_ATTACH);
}

/* A jump straight from one tap to another (a fast flick) still detaches before it attaches. */
static void test_flick(void)
{
    knob_t k;
    knob_init(&k);
    step_t last = STEP_NONE;
    feed(&k, code_of(5.0 / 6), MODE_STABLE, &last);
    CHECK(k.active == MODE_PS4);
    CHECK(knob_feed(&k, code_of(1.0 / 6)) == STEP_NONE);
    step_t seen[2 * MODE_STABLE];
    unsigned n = 0;
    for (unsigned i = 0; i < 2 * MODE_STABLE; i++) {
        step_t s = knob_feed(&k, code_of(1.0 / 6));
        if (s != STEP_NONE) {
            seen[n++] = s;
        }
    }
    CHECK(n == 2 && seen[0] == STEP_DETACH && seen[1] == STEP_ATTACH);
    CHECK(k.active == MODE_BLUETOOTH);
}

static void test_table(void)
{
    CHECK(mode_info(MODE_PS5)->vid == 0x054C && mode_info(MODE_PS5)->needs_auth);
    CHECK(mode_info(MODE_SWITCH)->needs_auth == false);
    CHECK(mode_info(MODE_BLUETOOTH)->link == LINK_BLUETOOTH);
    CHECK(mode_info((mode_t_)9) == NULL);
}

int main(void)
{
    test_positions();
    test_gaps();
    test_turn();
    test_flick();
    test_table();
    if (failures) {
        fprintf(stderr, "%d checks failed\n", failures);
        return EXIT_FAILURE;
    }
    puts("mode: all checks passed");
    return EXIT_SUCCESS;
}
