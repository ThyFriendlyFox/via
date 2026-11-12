/* DTMF in firmware: the panel's dialer digits, read by GPIO7's ADC at 8 kHz.
 *
 * TIP reaches the ADC through C29 and R28 onto a mid-rail bias (R29, R30): sim/dtmf_in.cir gives a
 * gain of 0.69 with under 0.01 dB of twist from 697 to 1633 Hz, the bias at 1.58 to 1.72 V. The
 * firmware takes the bias out (a slow average) and feeds signed samples here. A Goertzel filter per
 * DTMF frequency runs over the last DTMF_N samples every DTMF_HOP samples (205 and 102: 25.6 ms
 * windows, 12.8 ms apart), so a 50 ms digit fills at least 1 window.
 */
#ifndef HERALD_DTMF_H
#define HERALD_DTMF_H

#include <stdint.h>

#define DTMF_RATE 8000u
#define DTMF_N 205u
#define DTMF_HOP 102u

/* A window holds a digit when: its strongest row and column tone carry DTMF_PAIR_SHARE of its
 * energy, each beats the next tone of its group by 6 dB, the column (high) tone is at most
 * DTMF_TWIST_FWD_DB over the row tone and DTMF_TWIST_REV_DB under it (ITU-T Q.24, Table A-1: "+4 dB
 * to -8 dB"), and the window's RMS is DTMF_MIN_RMS codes or more (a -30 dBm tone reads about 22).
 * The share falls as a tone moves off its frequency: 0.98 on it, 0.42 at 1.5 % off, 0.23 at 2 %
 * off, 0.12 at 2.5 % off (the worst of the 16 keys, 205 samples). 0.35 takes 1.5 % and refuses 2 %. */
#define DTMF_PAIR_SHARE 0.35f
#define DTMF_GROUP_RATIO 4.0f /* 6 dB in power */
#define DTMF_TWIST_FWD_DB 4.0f
#define DTMF_TWIST_REV_DB 8.0f
#define DTMF_MIN_RMS 12.0f
/* Each half of the window holds DTMF_HALF_SHARE of its energy or more: the tone fills the window.
 * With 2 windows in a row needed, a 40 ms digit decodes at any phase and a 23 ms burst never does
 * (Q.24's operate and don't-operate durations). */
#define DTMF_HALF_SHARE 0.3f

typedef struct {
    int16_t ring[DTMF_N];
    uint16_t head;    /* where the next sample goes */
    uint16_t filled;  /* samples in the ring, up to DTMF_N */
    uint16_t since;   /* samples since the last window */
    char last;        /* the symbol the last window held, 0 for none */
    uint8_t agree;    /* windows in a row that held `last` */
    uint8_t reported; /* 1 once `last` was reported; cleared by a window with no symbol */
} dtmf_t;

void dtmf_init(dtmf_t *d);
/* Feeds 1 sample with the bias taken out. Returns a digit ('0'-'9', '*', '#', 'A'-'D') the moment
 * 2 windows in a row hold it, once per key press; 0 otherwise. */
char dtmf_feed(dtmf_t *d, int16_t sample);
/* The symbol 1 window holds, or 0: the test hook for the rules above. */
char dtmf_window(const int16_t *x, uint16_t n);

#endif
