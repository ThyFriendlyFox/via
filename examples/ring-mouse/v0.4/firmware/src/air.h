/* The air mouse: the gyroscope's turn rates to cursor counts.
 *
 * The IMU sits on the motion tile, which faces the finger's side: its frame is the radio tile's
 * turned about the finger's axis by AIR_TILE_DEG (ring.py: face_angle("motion")). Each reading
 * is turned back into the ring's frame: x across the crown, y along the finger toward its tip,
 * z out of the crown. Worn crown up, turning the hand left or right turns the ring about z and
 * moves the cursor across; pointing up or down turns it about x and moves the cursor up or down.
 * A roll about the finger moves nothing.
 *
 * The cursor follows the hand only while the thumb rests on the scroll strip (a clutch): lift the
 * thumb to bring the hand back without moving the cursor. Turn rates under AIR_DEADBAND are a
 * hand's tremor and the gyro's noise, and move nothing. AIR_GAIN counts a degree.
 */
#ifndef AIR_H
#define AIR_H

#include <stdbool.h>

#define AIR_TILE_DEG (-75.90f)
#define AIR_DEADBAND 3.0f /* degrees per second */
#define AIR_GAIN 20.0f    /* counts per degree the hand turns */

/* The chip's axes in the tile's frame (x toward the next tile round the ring, y toward the
 * fingertip, z out of the face), +1 or -1 on each. */
#define AIR_CHIP_X 1.0f
#define AIR_CHIP_Y 1.0f
#define AIR_CHIP_Z 1.0f

typedef struct {
    float residue_x; /* the fraction of a count not yet sent */
    float residue_y;
} air_t;

void air_init(air_t *a);

/* Turn the chip's frame into the ring's. */
void air_to_ring(const float chip[3], float ring[3]);

/* One gyro reading, in degrees per second in the chip's frame, `dt` seconds after the last; whether
 * the thumb rests on the strip. Writes the counts to move the cursor: +dx right, +dy down. */
void air_update(air_t *a, const float gyro_dps[3], bool touched, float dt, int *dx, int *dy);

#endif
