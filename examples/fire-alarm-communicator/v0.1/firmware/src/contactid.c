#include "contactid.h"

static const char HEX_KEYS[5] = {'*', '#', 'A', 'B', 'C'}; /* the values 11 to 15 */

int cid_value(char key)
{
    if (key >= '1' && key <= '9')
        return key - '0';
    if (key == '0')
        return 10;
    for (int i = 0; i < 5; i++)
        if (key == HEX_KEYS[i])
            return 11 + i;
    return -1;
}

static char key_of(int value)
{
    if (value >= 1 && value <= 9)
        return (char)('0' + value);
    if (value == 10)
        return '0';
    return HEX_KEYS[value - 11];
}

/* A decimal field: each digit 1-9 or '0' (10, read as 0); -1 for a hex digit, which no field
 * but the account takes. */
static int number(const char *d, int n)
{
    int v = 0;
    for (int i = 0; i < n; i++) {
        int x = cid_value(d[i]);
        if (x < 0 || x > 10)
            return -1;
        v = v * 10 + (x == 10 ? 0 : x);
    }
    return v;
}

char cid_checksum(const char *first15)
{
    int sum = 0;
    for (int i = 0; i < 15; i++) {
        int v = cid_value(first15[i]);
        if (v < 0)
            return 0;
        sum += v;
    }
    return key_of(15 - sum % 15); /* 1..15: 15 when the sum is already a multiple */
}

int cid_parse(const char *digits, cid_event_t *ev)
{
    int sum = 0;
    for (unsigned i = 0; i < CID_DIGITS; i++) {
        int v = cid_value(digits[i]);
        if (v < 0)
            return -1;
        sum += v;
    }
    if (sum % 15 != 0)
        return -1;
    int mt = number(digits + 4, 2);
    if (mt != 18 && mt != 98)
        return -1;
    int q = number(digits + 6, 1);
    if (q != 1 && q != 3 && q != 6)
        return -1;
    int code = number(digits + 7, 3), group = number(digits + 10, 2), zone = number(digits + 12, 3);
    if (code < 0 || group < 0 || zone < 0)
        return -1;
    for (int i = 0; i < 4; i++) {
        int v = cid_value(digits[i]);
        ev->account[i] = v == 10 ? '0' : v < 10 ? (char)('0' + v) : (char)('B' + v - 11);
    }
    ev->account[4] = '\0';
    ev->mt = (uint8_t)mt;
    ev->q = (uint8_t)q;
    ev->code = (uint16_t)code;
    ev->group = (uint8_t)group;
    ev->zone = (uint16_t)zone;
    switch (ev->code / 100) {
    case 1:
        ev->cls = CID_CLASS_ALARM;
        break;
    case 2:
        ev->cls = CID_CLASS_SUPERVISORY;
        break;
    case 3:
        ev->cls = CID_CLASS_TROUBLE;
        break;
    case 6:
        ev->cls = CID_CLASS_TEST;
        break;
    default:
        ev->cls = CID_CLASS_OTHER;
    }
    return 0;
}

/* ---- the call ----------------------------------------------------------------------------- */

static void enter(call_t *c, call_state_t s, call_out_t *out)
{
    c->state = s;
    c->timer = 0;
    switch (s) {
    case CALL_DIALTONE:
        out->tone = TONE_DIAL;
        break;
    case CALL_HANDSHAKE:
        out->tone = TONE_HANDSHAKE;
        break;
    case CALL_KISSOFF:
        out->tone = TONE_KISSOFF;
        break;
    default:
        out->tone = TONE_NONE;
    }
    if (s == CALL_MESSAGE)
        c->count = 0;
}

void call_init(call_t *c)
{
    c->state = CALL_IDLE;
    c->timer = 0;
    c->count = 0;
    c->bad = 0;
    c->msg[0] = '\0';
}

void call_hook(call_t *c, int offhook, call_out_t *out)
{
    out->event_ready = 0;
    if (offhook && c->state == CALL_IDLE) {
        c->bad = 0;
        enter(c, CALL_DIALTONE, out);
    } else if (!offhook) {
        enter(c, CALL_IDLE, out);
    }
}

void call_digit(call_t *c, char key, call_out_t *out)
{
    out->event_ready = 0;
    switch (c->state) {
    case CALL_DIALTONE:
        enter(c, CALL_DIALING, out); /* the first digit stops the dial tone */
        break;
    case CALL_DIALING:
        c->timer = 0;
        break;
    case CALL_MESSAGE:
        if (c->count < CID_DIGITS)
            c->msg[c->count++] = key;
        if (c->count == CID_DIGITS) {
            c->msg[CID_DIGITS] = '\0';
            if (cid_parse(c->msg, &out->event) == 0) {
                out->event_ready = 1;
                enter(c, CALL_KISSOFF, out);
            } else {
                /* No kissoff: the dialer sends the message again. */
                c->bad++;
                c->count = 0;
            }
        }
        break;
    default:
        break;
    }
}

void call_tick(call_t *c, uint32_t ms, call_out_t *out)
{
    out->event_ready = 0;
    c->timer += ms;
    switch (c->state) {
    case CALL_DIALING:
        if (c->timer >= DIAL_GAP_MS)
            enter(c, CALL_HANDSHAKE, out);
        break;
    case CALL_HANDSHAKE:
        /* 1400 Hz, a gap, 2300 Hz: the tone path's own sequencer plays the 3 parts. */
        if (c->timer >= 2 * HANDSHAKE_TONE_MS + HANDSHAKE_GAP_MS)
            enter(c, CALL_MESSAGE, out);
        break;
    case CALL_MESSAGE:
        if (c->timer >= MESSAGE_TIMEOUT_MS)
            enter(c, CALL_HANDSHAKE, out); /* nothing whole arrived: ask again */
        break;
    case CALL_KISSOFF:
        if (c->timer >= KISSOFF_MS)
            enter(c, CALL_MESSAGE, out); /* the dialer may send another, or hang up */
        break;
    default:
        break;
    }
}
