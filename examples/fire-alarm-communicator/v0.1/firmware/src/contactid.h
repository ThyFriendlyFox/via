/* Contact ID: the 16-digit message a fire panel's dialer sends, and the call that carries it.
 *
 * A message is ACCT (4) MT (2) Q (1) XYZ (3) GG (2) CCC (3) S (1). Each digit is a hex value sent
 * as a DTMF symbol: 1-9 as '1'-'9', 10 as '0', 11-15 (B-F) as '*', '#', 'A', 'B', 'C'; 'D' is never
 * sent. The values' sum, with S, is a multiple of 15, so S is 1 to 15 and never 0.
 *
 * The call: the dialer seizes the line (off hook), the board plays dial tone, the dialer dials the
 * station's number, the board answers with the handshake (1400 Hz 100 ms, silence 100 ms, 2300 Hz
 * 100 ms), the dialer sends the message (DTMF 50-60 ms on, 50-60 ms off), and the board
 * acknowledges each good message with the kissoff (1400 Hz, 750-1000 ms, within 1.25 s).
 *
 * The SIA DC-05 text was not read. These values come from spandsp's ademco_contactid.c and
 * Asterisk's app_alarmreceiver.c (both open receivers), the Zeta ZNDC fire dialer's manual (5.2-5.3)
 * and DMP's LT-1462, which cites DC-05-1999.09; the README's "The call" lists them.
 */
#ifndef HERALD_CONTACTID_H
#define HERALD_CONTACTID_H

#include <stdint.h>

#define CID_DIGITS 16u

typedef enum {
    CID_CLASS_OTHER = 0,
    CID_CLASS_ALARM,       /* event 1xx: 110 is a fire alarm */
    CID_CLASS_SUPERVISORY, /* 2xx: 200 is a fire supervisory */
    CID_CLASS_TROUBLE,     /* 3xx: 300 system trouble, 301 AC loss, 373 fire trouble */
    CID_CLASS_TEST,        /* 6xx: 602 is the periodic test */
} cid_class_t;

typedef struct {
    char account[5]; /* 4 hex digits, '0'-'9' and 'B'-'F', as the station prints it */
    uint8_t mt;      /* 18 (preferred) or 98 */
    uint8_t q;       /* 1 a new event, 3 a restore, 6 a status still present */
    uint16_t code;   /* XYZ */
    uint8_t group;   /* GG */
    uint16_t zone;   /* CCC */
    cid_class_t cls;
} cid_event_t;

/* The value a DTMF symbol carries in a message, 1 to 15; -1 for a symbol no message digit takes. */
int cid_value(char key);
/* 16 symbols to an event. 0 when the message is whole and its checksum holds; -1 otherwise. */
int cid_parse(const char *digits, cid_event_t *ev);
/* The checksum symbol that completes 15 digits; 0 when a digit is not a message digit. */
char cid_checksum(const char *first15);

/* ---- the call ----------------------------------------------------------------------------- */

typedef enum { TONE_NONE = 0, TONE_DIAL, TONE_HANDSHAKE, TONE_KISSOFF } tone_t;

typedef enum {
    CALL_IDLE = 0,  /* on hook */
    CALL_DIALTONE,  /* off hook: dial tone until the first digit */
    CALL_DIALING,   /* the station's number: digits until DIAL_GAP_MS of quiet */
    CALL_HANDSHAKE, /* playing 1400 Hz, a gap, 2300 Hz */
    CALL_MESSAGE,   /* collecting 16 digits */
    CALL_KISSOFF,   /* playing the kissoff for a good message */
} call_state_t;

#define DIAL_GAP_MS 1500u      /* quiet after the last dialled digit: the number is complete */
#define HANDSHAKE_TONE_MS 100u /* each of the 2 handshake tones */
#define HANDSHAKE_GAP_MS 100u
#define MESSAGE_TIMEOUT_MS 4000u /* from the handshake's end to a whole message */
#define KISSOFF_MS 800u          /* inside the 750-1000 ms the dialers expect */

typedef struct {
    call_state_t state;
    uint32_t timer; /* ms in the current state, or since the last digit while dialling */
    char msg[CID_DIGITS + 1];
    uint8_t count; /* digits of the message so far */
    uint8_t bad;   /* messages refused in this call */
} call_t;

typedef struct {
    tone_t tone;     /* what the tone path (GPIO14) plays now */
    int event_ready; /* 1 when `event` holds a message to send to the station */
    cid_event_t event;
} call_out_t;

void call_init(call_t *c);
/* Each input of the call: the hook (from line.h), a DTMF digit, and the time. */
void call_hook(call_t *c, int offhook, call_out_t *out);
void call_digit(call_t *c, char key, call_out_t *out);
void call_tick(call_t *c, uint32_t ms, call_out_t *out);

#endif
