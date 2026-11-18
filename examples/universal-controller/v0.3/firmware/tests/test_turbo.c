/* Host tests for the turbo patterns: cc -std=c11 -Wall -Wextra -Werror -I../src (make test). */
#include <stdio.h>
#include <string.h>

#include "turbo.h"

static int failures;

#define CHECK(cond)                                                                \
    do {                                                                           \
        if (!(cond)) {                                                             \
            fprintf(stderr, "%s:%d: CHECK(%s) failed\n", __FILE__, __LINE__, #cond); \
            failures++;                                                            \
        }                                                                          \
    } while (0)

/* Hold the button from `start` for `ms` milliseconds, 1 call a millisecond, and write what it reads
 * as into out[0..ms). Returns how many presses (released to pressed edges) it made. */
static unsigned run(const turbo_cfg_t *cfg, uint32_t start, uint32_t ms, char *out)
{
    turbo_state_t st;
    turbo_state_init(&st);
    unsigned presses = 0;
    bool last = false;
    for (uint32_t i = 0; i < ms; i++) {
        bool on = turbo_output(cfg, &st, true, start + i);
        if (out) {
            out[i] = on ? '1' : '0';
        }
        presses += on && !last;
        last = on;
    }
    return presses;
}

static turbo_cfg_t cfg_of(turbo_pattern_t p, uint8_t rate)
{
    turbo_cfg_t c;
    turbo_cfg_init(&c);
    c.pattern = p;
    c.rate = rate;
    return c;
}

static void test_off_passes_the_button_through(void)
{
    turbo_cfg_t c = cfg_of(TURBO_OFF, 0);
    turbo_state_t st;
    turbo_state_init(&st);
    CHECK(run(&c, 0, 1000, NULL) == 1);
    CHECK(!turbo_output(&c, &st, false, 5));
    CHECK(turbo_output(&c, &st, true, 6));
}

/* 10 a second: a 100 ms period, pressed for its first 50 ms, from the moment of the press. */
static void test_rapid_is_square_and_starts_pressed(void)
{
    turbo_cfg_t c = cfg_of(TURBO_RAPID, 2);
    char out[300];
    CHECK(turbo_period_ms(&c) == 100);
    CHECK(run(&c, 1234, 300, out) == 3);
    CHECK(out[0] == '1' && out[49] == '1' && out[50] == '0' && out[99] == '0' && out[100] == '1');
    for (uint8_t r = 0; r < TURBO_RATE_COUNT; r++) {
        c.rate = r;
        CHECK(run(&c, 0, 1000, NULL) == TURBO_RATES[r]);
    }
}

/* The same hold gives the same presses, whenever it starts: the timing is fixed. */
static void test_patterns_repeat_exactly(void)
{
    for (int p = TURBO_RAPID; p < TURBO_PATTERNS; p++) {
        turbo_cfg_t c = cfg_of((turbo_pattern_t)p, 2);
        char a[700], b[700];
        run(&c, 0, sizeof a, a);
        run(&c, 987654u, sizeof b, b);
        CHECK(memcmp(a, b, sizeof a) == 0);
    }
}

/* RAPID and STAGGER on 2 buttons pressed together: never both pressed, never both released for
 * more than an instant: they take turns. */
static void test_stagger_alternates_with_rapid(void)
{
    turbo_cfg_t r = cfg_of(TURBO_RAPID, 3), s = cfg_of(TURBO_STAGGER, 3);
    char a[500], b[500];
    run(&r, 40, sizeof a, a);
    run(&s, 40, sizeof b, b);
    CHECK(b[0] == '0' && b[24] == '0' && b[25] == '1');
    int both = 0, neither = 0;
    for (size_t i = 25; i < sizeof a; i++) {
        both += a[i] == '1' && b[i] == '1';
        neither += a[i] == '0' && b[i] == '0';
    }
    CHECK(both == 0 && neither == 0);
}

/* BURST: 3 presses at the rate, then released for as long as the button is held; let go and press
 * again, and it makes 3 more. */
static void test_burst_counts_and_waits_for_release(void)
{
    turbo_cfg_t c = cfg_of(TURBO_BURST, 3);
    CHECK(run(&c, 0, 5000, NULL) == 3);
    c.burst = 1;
    CHECK(run(&c, 0, 5000, NULL) == 1);
    c.burst = 0; /* treated as 1 */
    CHECK(run(&c, 0, 5000, NULL) == 1);

    c.burst = 3;
    turbo_state_t st;
    turbo_state_init(&st);
    unsigned presses = 0;
    bool last = false;
    for (uint32_t t = 0; t < 2000; t++) {
        bool held = t < 900 || t >= 1000; /* let go for 100 ms */
        bool on = turbo_output(&c, &st, held, t);
        presses += on && !last;
        last = on;
    }
    CHECK(presses == 6);
}

/* PULSE: groups of 3 at 20 a second (150 ms) with a 250 ms gap: a group every 400 ms. */
static void test_pulse_repeats_its_group(void)
{
    turbo_cfg_t c = cfg_of(TURBO_PULSE, 3);
    char out[1200];
    CHECK(run(&c, 0, sizeof out, out) == 9);
    for (int i = 150; i < 400; i++) {
        CHECK(out[i] == '0');
    }
    CHECK(out[400] == '1' && out[800] == '1');
    c.gap_ms = 0; /* no gap: the same as RAPID */
    turbo_cfg_t r = cfg_of(TURBO_RAPID, 3);
    char a[1000], b[1000];
    run(&c, 0, sizeof a, a);
    run(&r, 0, sizeof b, b);
    CHECK(memcmp(a, b, sizeof a) == 0);
}

/* Letting go reads released at once, in every pattern, at any point in its cycle. */
static void test_release_is_immediate(void)
{
    for (int p = TURBO_OFF; p < TURBO_PATTERNS; p++) {
        turbo_cfg_t c = cfg_of((turbo_pattern_t)p, 0);
        for (uint32_t hold = 1; hold < 600; hold += 37) {
            turbo_state_t st;
            turbo_state_init(&st);
            for (uint32_t t = 0; t < hold; t++) {
                turbo_output(&c, &st, true, t);
            }
            CHECK(!turbo_output(&c, &st, false, hold));
        }
    }
}

/* A press that spans the 32-bit millisecond wrap keeps its pattern. */
static void test_clock_wrap(void)
{
    turbo_cfg_t c = cfg_of(TURBO_RAPID, 1);
    char a[300], b[300];
    run(&c, 0xFFFFFF00u, sizeof a, a);
    run(&c, 0, sizeof b, b);
    CHECK(memcmp(a, b, sizeof a) == 0);
}

static void test_back_button_steps(void)
{
    turbo_cfg_t c;
    turbo_cfg_init(&c);
    const char *names[] = {"RAPID", "STAGGER", "BURST", "PULSE", "OFF"};
    for (int i = 0; i < 5; i++) {
        turbo_next_pattern(&c);
        CHECK(strcmp(turbo_name(c.pattern), names[i]) == 0);
    }
    CHECK(c.pattern == TURBO_OFF);
    for (unsigned i = 1; i <= TURBO_RATE_COUNT; i++) {
        turbo_next_rate(&c);
        CHECK(c.rate == i % TURBO_RATE_COUNT);
    }
}

int main(void)
{
    test_off_passes_the_button_through();
    test_rapid_is_square_and_starts_pressed();
    test_patterns_repeat_exactly();
    test_stagger_alternates_with_rapid();
    test_burst_counts_and_waits_for_release();
    test_pulse_repeats_its_group();
    test_release_is_immediate();
    test_clock_wrap();
    test_back_button_steps();
    if (failures) {
        fprintf(stderr, "turbo: %d check(s) failed\n", failures);
        return 1;
    }
    puts("turbo: every check passed");
    return 0;
}
