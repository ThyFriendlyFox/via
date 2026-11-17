/* Host tests for Lark's light rules: make -C firmware test */
#include <stdio.h>
#include <stdlib.h>

#include "light.h"

static int failures;

#define CHECK(cond)                                                    \
    do {                                                               \
        if (!(cond)) {                                                 \
            printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);     \
            failures++;                                                \
        }                                                              \
    } while (0)

static void test_mode(void)
{
    CHECK(lark_mode_from_hall(0, 0) == LARK_MODE_VOICE);
    CHECK(lark_mode_from_hall(1, 0) == LARK_MODE_ALEXA);
    CHECK(lark_mode_from_hall(0, 1) == LARK_MODE_APPLE);
    CHECK(lark_mode_from_hall(1, 1) == LARK_MODE_VOICE); /* no place of the slider: stay offline */
}

static void test_mix_budget(void)
{
    /* At every level and colour temperature the 2 shares stay inside the budget, and each is 0 or
     * at least the HV9961's minimum. */
    for (unsigned level = 0; level <= 1000; level += 5) {
        for (unsigned k = 2500; k <= 5200; k += 50) {
            unsigned w, c;
            lark_mix(level, k, LARK_BUDGET, &w, &c);
            CHECK(w + c <= LARK_BUDGET);
            CHECK(w == 0 || w >= LARK_SHARE_MIN);
            CHECK(c == 0 || c >= LARK_SHARE_MIN);
        }
    }
}

static void test_mix_ends(void)
{
    unsigned w, c;
    lark_mix(1000, 2700, LARK_BUDGET, &w, &c);
    CHECK(w == 900 && c == 0); /* all warm, at the budget, not at one string's 100 % */
    lark_mix(1000, 5000, LARK_BUDGET, &w, &c);
    CHECK(w == 0 && c == 900);
    lark_mix(1000, 3500, LARK_BUDGET, &w, &c);
    CHECK(w + c == 900 && w > 0 && c > 0);
    lark_mix(0, 3500, LARK_BUDGET, &w, &c);
    CHECK(w == 0 && c == 0);
    /* 10 % of the budget near the cool end: the warm share (4) rounds to 0, the cool share (86)
     * up to the HV9961's floor. The dimmest light is one string at 13.5 %. */
    lark_mix(100, 4900, LARK_BUDGET, &w, &c);
    CHECK(w == 0 && c == LARK_SHARE_MIN);
    lark_mix(20, 3500, LARK_BUDGET, &w, &c);
    CHECK(w == 0 && c == 0); /* 18 in all: nearer 0 than the floor for each */
}

static void test_mix_monotonic(void)
{
    /* Warmer asks for more warm and less cool at a level where neither rounds. */
    unsigned prev_w = 0, prev_c = 1000;
    for (unsigned k = 2700; k <= 5000; k += 100) {
        unsigned w, c;
        lark_mix(1000, k, LARK_BUDGET, &w, &c);
        if (k > 2700) {
            CHECK(w <= prev_w);
            CHECK(c >= prev_c);
        }
        prev_w = w;
        prev_c = c;
    }
}

static void test_line(void)
{
    /* VBUS_SENSE: 2.43 V at 198 V (driver/design.py). */
    CHECK(lark_vbus_v(2435) == 198);
    CHECK(lark_foldback_line(900, 160) == 900);
    CHECK(lark_foldback_line(900, 110) == 900);
    CHECK(lark_foldback_line(900, 103) == 450);
    CHECK(lark_foldback_line(900, 90) == 450);
    unsigned prev = 0;
    for (unsigned v = 95; v <= 115; v++) {
        unsigned b = lark_foldback_line(900, v);
        CHECK(b >= prev);
        prev = b;
    }
}

static void test_temperature(void)
{
    /* The NTC divider's readings (brain/sim/ntc_divider.expect.json): 1.58 V near 85 C, 1.085 V
     * near 105 C, about 3.0 V at 25 C. */
    int t85 = lark_disc_temp_dc(1580), t105 = lark_disc_temp_dc(1085), t25 = lark_disc_temp_dc(3000);
    CHECK(abs(t85 - 850) <= 20);
    CHECK(abs(t105 - 1050) <= 20);
    CHECK(abs(t25 - 250) <= 20);
    CHECK(lark_disc_temp_dc(0) > 1100); /* a shorted NTC turns the light off */
    CHECK(lark_foldback_temp(900, 600) == 900);
    CHECK(lark_foldback_temp(900, 850) == 900);
    CHECK(lark_foldback_temp(900, 950) == 540);
    CHECK(lark_foldback_temp(900, 1050) == 180);
    CHECK(lark_foldback_temp(900, 1080) == 180);
    CHECK(lark_foldback_temp(900, 1101) == 0);
}

int main(void)
{
    test_mode();
    test_mix_budget();
    test_mix_ends();
    test_mix_monotonic();
    test_line();
    test_temperature();
    if (failures) {
        printf("%d failures\n", failures);
        return 1;
    }
    printf("test_light: all passed\n");
    return 0;
}
