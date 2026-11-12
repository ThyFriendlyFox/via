/* Host tests of the air mouse: a hand's turn in the ring's frame, as the motion tile's chip reads it,
 * back to cursor counts. */
#include <math.h>
#include <stdio.h>

#include "air.h"

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

#define RATE 0.01f /* 100 readings a second */

/* What the chip on the motion tile reads for a turn of the ring at `ring` degrees per second: the
 * ring's frame turned into the tile's, the inverse of air_to_ring. */
static void chip_reading(const float ring[3], float chip[3])
{
    float c = cosf(AIR_TILE_DEG * 3.14159265f / 180.0f), s = sinf(AIR_TILE_DEG * 3.14159265f / 180.0f);
    chip[0] = (c * ring[0] - s * ring[2]) / AIR_CHIP_X;
    chip[1] = ring[1] / AIR_CHIP_Y;
    chip[2] = (s * ring[0] + c * ring[2]) / AIR_CHIP_Z;
}

/* Turn the ring at `ring` for `n` readings with the thumb down or up; the counts it moves. */
static void turn(const float ring[3], int n, bool touched, int *x, int *y)
{
    air_t a;
    air_init(&a);
    float chip[3];
    chip_reading(ring, chip);
    *x = *y = 0;
    for (int i = 0; i < n; i++) {
        int dx, dy;
        air_update(&a, chip, touched, RATE, &dx, &dy);
        *x += dx;
        *y += dy;
    }
}

static void test_the_tiles_angle_is_turned_back(void)
{
    float ring[3] = {12.0f, -5.0f, 30.0f}, chip[3], back[3];
    chip_reading(ring, chip);
    CHECK(fabsf(chip[0] - ring[0]) > 1.0f, "the chip reads another frame than the ring's");
    air_to_ring(chip, back);
    for (int i = 0; i < 3; i++) {
        CHECK(fabsf(back[i] - ring[i]) < 1e-3f, "axis %d: %.4f back, %.4f turned", i, back[i], ring[i]);
    }
}

static void test_turning_left_moves_the_cursor_left_only(void)
{
    float ring[3] = {0.0f, 0.0f, 23.0f}; /* about z: the hand turns left at 23 degrees a second */
    int x, y;
    turn(ring, 100, true, &x, &y);
    /* 1 s at (23 - 3) degrees a second past the deadband, 20 counts a degree: 400 counts. */
    CHECK(x == -400, "left turn: %d counts across, want -400", x);
    CHECK(y == 0, "left turn: %d counts down, want 0", y);
}

static void test_pointing_up_moves_the_cursor_up_only(void)
{
    float ring[3] = {13.0f, 0.0f, 0.0f}; /* about x: the finger points up */
    int x, y;
    turn(ring, 50, true, &x, &y);
    /* 0.5 s at 10 degrees a second past the deadband: 100 counts up. */
    CHECK(y == -100, "pointing up: %d counts down, want -100", y);
    CHECK(x == 0, "pointing up: %d counts across, want 0", x);
}

static void test_a_roll_about_the_finger_moves_nothing(void)
{
    float ring[3] = {0.0f, 90.0f, 0.0f};
    int x, y;
    turn(ring, 100, true, &x, &y);
    CHECK(x == 0 && y == 0, "a roll: %d, %d counts, want none", x, y);
}

static void test_a_tremor_moves_nothing(void)
{
    float ring[3] = {2.5f, 0.0f, -2.9f}; /* under 3 degrees a second each */
    int x, y;
    turn(ring, 300, true, &x, &y);
    CHECK(x == 0 && y == 0, "a tremor: %d, %d counts, want none", x, y);
}

static void test_the_thumb_lifted_moves_nothing(void)
{
    float ring[3] = {40.0f, 0.0f, 40.0f};
    int x, y;
    turn(ring, 100, false, &x, &y);
    CHECK(x == 0 && y == 0, "thumb up: %d, %d counts, want none", x, y);
}

static void test_fractions_of_a_count_add_up(void)
{
    /* 3.5 degrees a second is 0.5 past the deadband: 0.1 counts a reading, 10 counts in 1 s. */
    float ring[3] = {0.0f, 0.0f, -3.5f};
    int x, y;
    turn(ring, 100, true, &x, &y);
    CHECK(x >= 9 && x <= 10, "a slow turn right: %d counts, want 10 (9 for the last fraction)", x);
}

int main(void)
{
    test_the_tiles_angle_is_turned_back();
    test_turning_left_moves_the_cursor_left_only();
    test_pointing_up_moves_the_cursor_up_only();
    test_a_roll_about_the_finger_moves_nothing();
    test_a_tremor_moves_nothing();
    test_the_thumb_lifted_moves_nothing();
    test_fractions_of_a_count_add_up();
    if (failures) {
        printf("%d failures\n", failures);
        return 1;
    }
    printf("all air tests passed\n");
    return 0;
}
