/* Host tests of the scroll strip's decoder: a thumb modelled as a bump of capacitance sliding
 * along the 6 stripes, read the way the TSC reads them. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "strip.h"

#define STRIPES 6
#define PITCH 1.55f /* mm from 1 stripe to the next (footprints/make_footprints.py) */
#define UNTOUCHED 1000
#define DEPTH 140.0f /* the count a stripe loses under the middle of a thumb */
#define SIGMA 1.6f   /* mm: how far the thumb's bump spreads */

static int failures;

#define CHECK(cond, ...)                                                                                    \
    do {                                                                                                    \
        if (!(cond)) {                                                                                      \
            failures++;                                                                                     \
            printf("FAIL %s:%d: ", __FILE__, __LINE__);                                                     \
            printf(__VA_ARGS__);                                                                            \
            printf("\n");                                                                                   \
        }                                                                                                   \
    } while (0)

/* The 3 channels' counts with a thumb centred `at` mm from the first stripe (none when depth is 0). */
static void read(float at, float depth, uint16_t out[3])
{
    float drop[3] = {0, 0, 0};
    for (int k = 0; k < STRIPES; k++) {
        float x = (k * PITCH - at) / SIGMA;
        drop[k % 3] += depth * expf(-0.5f * x * x);
    }
    for (int c = 0; c < 3; c++) {
        out[c] = (uint16_t)(UNTOUCHED - (int)lroundf(drop[c]));
    }
}

/* Slide from `from` to `to` mm in steps of `step` mm; the detents reported along the way. */
static int slide(strip_t *s, float from, float to, float step)
{
    uint16_t c[3];
    int total = 0;
    float dir = to > from ? 1.0f : -1.0f;
    for (float at = from; dir * (to - at) >= -1e-4f; at += dir * step) {
        read(at, DEPTH, c);
        total += strip_update(s, c);
    }
    return total;
}

static void start(strip_t *s)
{
    uint16_t c[3];
    read(0, 0, c);
    strip_init(s, c);
}

static void touch_down(strip_t *s, float at)
{
    uint16_t c[3];
    read(at, DEPTH, c);
    CHECK(strip_update(s, c) == 0, "the first touched reading scrolls nothing");
    CHECK(s->touched, "a thumb at %.2f mm is a touch", at);
}

static void lift(strip_t *s)
{
    uint16_t c[3];
    read(0, 0, c);
    CHECK(strip_update(s, c) == 0, "lifting scrolls nothing");
    CHECK(!s->touched, "no thumb is no touch");
}

static void test_untouched_strip_scrolls_nothing(void)
{
    strip_t s;
    start(&s);
    uint16_t c[3];
    int total = 0;
    for (int i = 0; i < 500; i++) {
        uint16_t drift = (uint16_t)(i / 25); /* the counts creep up 20 over the run */
        c[0] = c[1] = c[2] = (uint16_t)(UNTOUCHED + drift);
        total += strip_update(&s, c);
    }
    CHECK(total == 0 && !s.touched, "drift alone: %d detents, touched %d", total, s.touched);
    /* The baseline followed the drift, so a slow fall back is no touch either. */
    for (int i = 0; i < 100; i++) {
        c[0] = c[1] = c[2] = (uint16_t)(UNTOUCHED + 20 - i / 10);
        total += strip_update(&s, c);
    }
    CHECK(total == 0 && !s.touched, "drift back: %d detents", total);
}

static void test_a_light_brush_is_no_touch(void)
{
    strip_t s;
    start(&s);
    uint16_t c[3];
    read(3.0f, 30.0f, c); /* a fifth of a thumb's depth: a sleeve, a drop of water */
    CHECK(strip_update(&s, c) == 0 && !s.touched, "a light brush is no touch");
}

static void test_toward_the_hand_scrolls_down(void)
{
    strip_t s;
    start(&s);
    touch_down(&s, 0.0f);
    /* 1 cycle of 3 stripes is 4.65 mm: 4 detents. */
    int n = slide(&s, 0.0f, 3 * PITCH, 0.1f);
    CHECK(n == -4, "a cycle toward the hand: %d detents, want -4", n);
    lift(&s);
}

static void test_toward_the_fingertip_scrolls_up(void)
{
    strip_t s;
    start(&s);
    touch_down(&s, 5 * PITCH);
    int n = slide(&s, 5 * PITCH, 2 * PITCH, 0.1f);
    CHECK(n == 4, "a cycle toward the fingertip: %d detents, want 4", n);
    lift(&s);
}

static void test_across_the_whole_strip(void)
{
    strip_t s;
    start(&s);
    touch_down(&s, 0.0f);
    /* The 6 stripes span 5 pitches, 5/3 of a cycle: 6.67 detents if the angle ran even to the ends.
     * At each end the thumb's bump hangs off the last stripe and the angle moves less, so 6 or 7. */
    int n = slide(&s, 0.0f, 5 * PITCH, 0.05f);
    CHECK(n == -6 || n == -7, "the whole strip down: %d detents, want -6 or -7", n);
    int back = slide(&s, 5 * PITCH, 0.0f, 0.05f);
    CHECK(back == -n, "and back up: %d detents, want %d", back, -n);
}

static void test_a_resting_thumb_scrolls_nothing(void)
{
    strip_t s;
    start(&s);
    touch_down(&s, 2.0f);
    uint16_t c[3];
    int total = 0;
    for (int i = 0; i < 200; i++) {
        read(2.0f + 0.02f * (float)((i % 5) - 2), DEPTH, c); /* a tremor of 0.04 mm */
        total += strip_update(&s, c);
    }
    CHECK(total == 0, "a resting thumb: %d detents", total);
}

static void test_a_fast_flick_counts_every_detent(void)
{
    strip_t s;
    start(&s);
    touch_down(&s, 0.0f);
    /* 0.7 mm a reading, under half a cycle (2.3 mm): the unwrap still holds. */
    int n = slide(&s, 0.0f, 3 * PITCH, 0.7f);
    CHECK(n <= -3 && n >= -5, "a fast flick down a cycle: %d detents, want about -4", n);
}

static void test_each_touch_starts_afresh(void)
{
    strip_t s;
    start(&s);
    touch_down(&s, 0.0f);
    int n = slide(&s, 0.0f, 1.0f, 0.1f);
    lift(&s);
    touch_down(&s, 6.0f); /* put down elsewhere: no jump from where the last touch ended */
    uint16_t c[3];
    read(6.0f, DEPTH, c);
    n = strip_update(&s, c);
    CHECK(n == 0, "a new touch elsewhere: %d detents", n);
}

int main(void)
{
    test_untouched_strip_scrolls_nothing();
    test_a_light_brush_is_no_touch();
    test_toward_the_hand_scrolls_down();
    test_toward_the_fingertip_scrolls_up();
    test_across_the_whole_strip();
    test_a_resting_thumb_scrolls_nothing();
    test_a_fast_flick_counts_every_detent();
    test_each_touch_starts_afresh();
    if (failures) {
        printf("%d failures\n", failures);
        return 1;
    }
    printf("all strip tests passed\n");
    return 0;
}
