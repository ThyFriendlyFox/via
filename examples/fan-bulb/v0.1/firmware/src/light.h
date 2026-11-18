/* Lark v0.1: the light's rules, as the brain's ESP32-C6 runs them.
 *
 * The parts of the firmware the boards depend on, kept free of the radio stacks and ESP-IDF so
 * that the host tests (tests/test_light.c) run them:
 *
 * - the mode slider: which of the 2 Hall switches on the driver sees the magnet;
 * - the mix: a level and a colour temperature into the 2 strings' shares, inside the power budget;
 * - the 2 foldbacks: the bus's valley (low mains) and the light disc's temperature (its NTC).
 *
 * Every share is in permille of one string's full current, 100 mA (driver/design.py: R_CS 2.74
 * ohm at V(LD) 1.48 V). U1's LEDC drives DIM_W and DIM_C at that duty.
 */
#ifndef LARK_LIGHT_H
#define LARK_LIGHT_H

/* Warm and cool together draw at most 90 % of one string's full current: 8.3 W from the bus,
 * where the bulk capacitors' ripple stays under their 47 mA rating at every corner
 * (driver/sim/bus_valley.cir). At 100 % a capacitor at +20 % beside 2 at -20 % carries 48.3 mA. */
#define LARK_BUDGET 900u
/* Below 13.5 % the HV9961's LD is under 0.2 V and the controller stops (DS20005588B): a share
 * between 0 and this is rounded to the nearer of the 2. */
#define LARK_SHARE_MIN 135u
#define LARK_CCT_WARM 2700u /* the warm string's LEDs (light/design.py) */
#define LARK_CCT_COOL 5000u /* the cool string's */

typedef enum {
    LARK_MODE_VOICE = 0, /* the slider in the middle: voice in the bulb only, no radio joins */
    LARK_MODE_ALEXA = 1, /* the magnet over U5: Zigbee 3.0, to an Echo with a Zigbee hub */
    LARK_MODE_APPLE = 2, /* the magnet over U6: HomeKit over Thread */
} lark_mode;

/* The slider's place from the 2 Hall switches. Each DRV5033 pulls its output low while the
 * magnet is over it; `a_low` is HALL_A (U5), `b_low` HALL_B (U6). Both low is no place the slider
 * has: the bulb stays in voice mode. */
lark_mode lark_mode_from_hall(int a_low, int b_low);

/* The 2 strings' shares for a level (0 to 1000 permille of the budget) and a colour temperature
 * in kelvin, mixed on the mired scale. The 2 shares sum to at most `budget` (LARK_BUDGET or less,
 * after the foldbacks). */
void lark_mix(unsigned level, unsigned cct_k, unsigned budget, unsigned *warm, unsigned *cool);

/* The bus's lowest voltage in each 120 Hz valley, from VBUS_SENSE's millivolts: 2 M over 24.9k
 * (driver/design.py, R13-R15). */
unsigned lark_vbus_v(unsigned sense_mv);

/* The budget at a bus valley: LARK_BUDGET at 110 V and over; down in a line to half of it at
 * 103 V, where the strings' 77.5 V over the HV9961's duty limit of 0.75 meets the bus
 * (driver/sim/bus_valley.expect.json); half under that. */
unsigned lark_foldback_line(unsigned budget, unsigned vbus_valley_v);

/* The light disc's temperature in tenths of a degree C from the NTC's millivolts: RT1 100k,
 * B 4250 K, under R8 10k to 3.3 V (brain/sim/ntc_divider.cir). */
int lark_disc_temp_dc(unsigned ntc_mv);

/* The budget at a disc temperature: whole to 85 C, down in a line to a fifth at 105 C, and off
 * over 110 C, where something has failed (brain/sim/ntc_divider.expect.json). */
unsigned lark_foldback_temp(unsigned budget, int disc_dc);

#endif
