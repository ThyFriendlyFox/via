/* Host tests for Herald's firmware logic: cc -std=c11 -Wall -Wextra -Werror -Isrc (make test). */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "contactid.h"
#include "dtmf.h"
#include "line.h"
#include "zone.h"

static int failures;

#define CHECK(cond)                                                                \
    do {                                                                           \
        if (!(cond)) {                                                             \
            fprintf(stderr, "%s:%d: CHECK(%s) failed\n", __FILE__, __LINE__, #cond); \
            failures++;                                                            \
        }                                                                          \
    } while (0)

/* ---- zones -------------------------------------------------------------------------------- */

/* Each deck's reading as written and its least and greatest corner (`workcenter sim . --deck`). */
static void test_zone_decks(void)
{
    const double shorted[] = {0.144886, 0.140247, 0.151197};
    const double normal[] = {1.65499, 1.55479, 1.75664, 1.69677, 1.59686, 1.79811};
    const double open[] = {3.2853, 3.18612, 3.3843};
    for (unsigned i = 0; i < 3; i++)
        CHECK(zone_classify((uint16_t)(shorted[i] * 1000)) == ZONE_ACTIVE);
    for (unsigned i = 0; i < 6; i++)
        CHECK(zone_classify((uint16_t)(normal[i] * 1000)) == ZONE_NORMAL);
    for (unsigned i = 0; i < 3; i++)
        CHECK(zone_classify((uint16_t)(open[i] * 1000)) == ZONE_OPEN);
    /* Between the bands: neither normal nor a state the panel set. */
    CHECK(zone_classify(800) == ZONE_FAULT);
    CHECK(zone_classify(2500) == ZONE_FAULT);
}

/* A contact that bounces for 50 ms, then closes: 1 change, after 100 ms of closed readings. */
static void test_zone_debounce(void)
{
    zone_t z;
    zone_init(&z);
    int changes = 0;
    for (int i = 0; i < 5; i++) {
        changes += zone_feed(&z, 100);
        changes += zone_feed(&z, 1650);
    }
    CHECK(changes == 0 && z.state == ZONE_NORMAL);
    for (unsigned i = 0; i < ZONE_STABLE - 1; i++)
        changes += zone_feed(&z, 100);
    CHECK(changes == 0);
    changes += zone_feed(&z, 100);
    CHECK(changes == 1 && z.state == ZONE_ACTIVE);
}

/* ---- the hook ------------------------------------------------------------------------------ */

static void test_line(void)
{
    line_t l;
    line_init(&l);
    int changes = 0;
    /* The decks' ends: on hook 0.027 to 0.040 V, off hook 0.78 to 1.32 V. */
    for (int i = 0; i < 100; i++)
        changes += line_feed(&l, 40);
    CHECK(changes == 0 && !l.offhook);
    for (unsigned i = 0; i < LINE_STABLE; i++)
        changes += line_feed(&l, 776);
    CHECK(changes == 1 && l.offhook);
    /* A 10 ms dip is no hang-up. */
    for (int i = 0; i < 10; i++)
        changes += line_feed(&l, 30);
    for (int i = 0; i < 5; i++)
        changes += line_feed(&l, 1300);
    CHECK(changes == 1 && l.offhook);
}

/* ---- DTMF ---------------------------------------------------------------------------------- */

static const double ROWS[4] = {697, 770, 852, 941};
static const double COLS[4] = {1209, 1336, 1477, 1633};
static const char *KEYPAD = "123A456B789C*0#D";

static unsigned noise_state = 12345u;
static double noise(void)
{
    noise_state = noise_state * 1103515245u + 12345u;
    return ((double)((noise_state >> 8) & 0xFFFF) / 65535.0 - 0.5) * 2.0;
}

/* A dBm level on the 600 ohm line to ADC codes of peak, through the path's 0.69 gain onto a 12-bit
 * ADC that spans 3.1 V. */
static double codes_peak(double dbm)
{
    double vrms = sqrt(0.001 * 600.0 * pow(10.0, dbm / 10.0));
    return vrms * sqrt(2.0) * 0.69 / 3.1 * 4096.0;
}

typedef struct {
    double dbm;       /* each tone's level */
    double twist_db;  /* the column tone over the row tone */
    double freq_err;  /* both tones off by this fraction */
    double noise_pk;  /* uniform noise, codes peak */
    unsigned on_ms, off_ms;
    unsigned lead;    /* samples of silence before the first key */
} play_t;

/* Plays a string of keys through a decoder and returns what it reported. */
static void play(const char *keys, const play_t *p, char *heard, size_t cap)
{
    dtmf_t d;
    dtmf_init(&d);
    size_t n = 0;
    double t = 0.0;
    for (unsigned s = 0; s < p->lead; s++, t += 1.0 / DTMF_RATE)
        dtmf_feed(&d, (int16_t)lround(p->noise_pk * noise()));
    for (const char *k = keys; *k; k++) {
        const char *at = strchr(KEYPAD, *k);
        int i = (int)(at - KEYPAD);
        double fr = ROWS[i / 4] * (1.0 + p->freq_err), fc = COLS[i % 4] * (1.0 + p->freq_err);
        double ar = codes_peak(p->dbm), ac = ar * pow(10.0, p->twist_db / 20.0);
        unsigned on = p->on_ms * DTMF_RATE / 1000u, off = p->off_ms * DTMF_RATE / 1000u;
        for (unsigned s = 0; s < on + off; s++, t += 1.0 / DTMF_RATE) {
            double x = p->noise_pk * noise();
            if (s < on)
                x += ar * sin(2 * M_PI * fr * t) + ac * sin(2 * M_PI * fc * t);
            char got = dtmf_feed(&d, (int16_t)lround(x));
            if (got && n + 1 < cap)
                heard[n++] = got;
        }
    }
    heard[n] = '\0';
}

static void test_dtmf(void)
{
    char heard[64];
    const play_t clean = {-10.0, 0.0, 0.0, 0.0, 50, 50, 0};
    play(KEYPAD, &clean, heard, sizeof heard);
    CHECK(strcmp(heard, KEYPAD) == 0);

    /* What a receiver must take (ITU-T Q.24, Table A-1): 0 to -25 dBm, the high tone 4 dB over to
     * 8 dB under the low, 1.5 % off frequency, 40 ms digits; and noise. Each decodes once per key. */
    const play_t cases[] = {
        {-25.0, 0.0, 0.0, 0.0, 50, 50, 0},
        {0.0, 0.0, 0.0, 0.0, 50, 50, 0},
        {-10.0, 3.5, 0.0, 0.0, 50, 50, 0},
        {-10.0, -7.5, 0.0, 0.0, 50, 50, 0},
        {-10.0, 0.0, 0.015, 0.0, 50, 50, 0},
        {-10.0, 0.0, -0.015, 0.0, 50, 50, 0},
        {-15.0, 0.0, 0.0, 20.0, 50, 50, 0},
        {-10.0, 0.0, 0.0, 0.0, 60, 60, 0},
        {-10.0, 0.0, 0.0, 0.0, 40, 40, 0},
    };
    for (unsigned i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        play("1830181602001", &cases[i], heard, sizeof heard);
        if (strcmp(heard, "1830181602001") != 0)
            fprintf(stderr, "case %u heard %s\n", i, heard);
        CHECK(strcmp(heard, "1830181602001") == 0);
    }

    /* What it must refuse: the high tone 6 dB over or 10 dB under the low, 3.5 % off frequency,
     * and -40 dBm (under the decoder's floor). */
    const play_t refused[] = {
        {-10.0, 6.0, 0.0, 0.0, 50, 50, 0},
        {-10.0, -10.0, 0.0, 0.0, 50, 50, 0},
        {-10.0, 0.0, 0.035, 0.0, 50, 50, 0},
        {-10.0, 0.0, -0.035, 0.0, 50, 50, 0},
        {-40.0, 0.0, 0.0, 0.0, 50, 50, 0},
    };
    for (unsigned i = 0; i < sizeof refused / sizeof refused[0]; i++) {
        play("5", &refused[i], heard, sizeof heard);
        if (heard[0] != '\0')
            fprintf(stderr, "refused case %u heard %s\n", i, heard);
        CHECK(heard[0] == '\0');
    }

    /* Duration at every phase against the windows: 40 ms decodes, 23 ms never does. */
    for (unsigned lead = 0; lead < DTMF_HOP; lead += 7) {
        const play_t p40 = {-10.0, 0.0, 0.0, 0.0, 40, 40, lead};
        const play_t p23 = {-10.0, 0.0, 0.0, 0.0, 23, 40, lead};
        char k40[8], k23[8];
        play("7", &p40, k40, sizeof k40);
        play("7", &p23, k23, sizeof k23);
        if (strcmp(k40, "7") != 0 || k23[0] != '\0')
            fprintf(stderr, "lead %u: 40 ms heard '%s', 23 ms heard '%s'\n", lead, k40, k23);
        CHECK(strcmp(k40, "7") == 0);
        CHECK(k23[0] == '\0');
    }
    int16_t tone[DTMF_N];
    for (unsigned s = 0; s < DTMF_N; s++)
        tone[s] = (int16_t)lround(codes_peak(-10.0) * sin(2 * M_PI * 1400.0 * s / DTMF_RATE));
    CHECK(dtmf_window(tone, DTMF_N) == 0);
}

/* ---- Contact ID ---------------------------------------------------------------------------- */

static void test_contactid(void)
{
    cid_event_t ev;
    /* Account 1234, a new fire alarm (110) in group 01, zone 015. */
    char msg[17] = "123418111001015";
    msg[15] = cid_checksum(msg);
    msg[16] = '\0';
    CHECK(msg[15] != 0);
    CHECK(cid_parse(msg, &ev) == 0);
    CHECK(strcmp(ev.account, "1234") == 0 && ev.mt == 18 && ev.q == 1 && ev.code == 110 &&
          ev.group == 1 && ev.zone == 15 && ev.cls == CID_CLASS_ALARM);
    /* 1 digit changed: the checksum no longer holds. */
    msg[13] = msg[13] == '1' ? '2' : '1';
    CHECK(cid_parse(msg, &ev) == -1);
    /* A 0 counts as 10 in the sum: "1234 18 1 602 00 000" sums to 88, so the checksum is 2. */
    CHECK(cid_checksum("123418160200000") == '2');
    CHECK(cid_parse("1234181602000002", &ev) == 0 && ev.cls == CID_CLASS_TEST && ev.code == 602);
    CHECK(cid_parse("1234181602000003", &ev) == -1);
    /* The checksums 11 to 15 go as '*', '#', 'A', 'B', 'C'; a sum already a multiple of 15 takes
     * 'C' (15), never 0. "1234 18 1 602 00 001" sums to 79: 11. Zone 017 sums to 91: 14. Zone 016
     * sums to 90, a multiple of 15: 15. */
    CHECK(cid_checksum("123418160200001") == '*');
    CHECK(cid_checksum("123418160200017") == 'B');
    CHECK(cid_checksum("123418160200016") == 'C');
    CHECK(cid_parse("123418160200016C", &ev) == 0 && ev.zone == 16);
    CHECK(cid_parse("123418160200017B", &ev) == 0 && ev.zone == 17);
    /* An account with hex digits: B and C are sent as '*' and '#'. */
    char hexacct[17] = "*#1218111001002";
    hexacct[15] = cid_checksum(hexacct);
    hexacct[16] = '\0';
    CHECK(cid_parse(hexacct, &ev) == 0 && strcmp(ev.account, "BC12") == 0);
    /* Hex digits in a decimal field are refused, and 'D' is never a message digit. */
    CHECK(cid_parse("12341811*0010150", &ev) == -1);
    CHECK(cid_value('D') == -1);
}

/* A whole call: off hook, dial tone, the number, the handshake, the message as tones through the
 * DTMF decoder, the kissoff. */
static void test_call(void)
{
    call_t c;
    call_out_t out;
    call_init(&c);
    call_hook(&c, 1, &out);
    CHECK(c.state == CALL_DIALTONE && out.tone == TONE_DIAL);
    for (const char *k = "5551234"; *k; k++) {
        call_digit(&c, *k, &out);
        call_tick(&c, 100, &out);
    }
    CHECK(c.state == CALL_DIALING && out.tone == TONE_NONE);
    call_tick(&c, DIAL_GAP_MS, &out);
    CHECK(c.state == CALL_HANDSHAKE && out.tone == TONE_HANDSHAKE);
    call_tick(&c, 2 * HANDSHAKE_TONE_MS + HANDSHAKE_GAP_MS, &out);
    CHECK(c.state == CALL_MESSAGE);

    char msg[17] = "432118120001008";
    msg[15] = cid_checksum(msg);
    msg[16] = '\0';
    char heard[64];
    const play_t p = {-12.0, 1.0, 0.004, 8.0, 50, 50, 0};
    play(msg, &p, heard, sizeof heard);
    CHECK(strcmp(heard, msg) == 0);
    int events = 0;
    for (const char *k = heard; *k; k++) {
        call_digit(&c, *k, &out);
        events += out.event_ready;
    }
    CHECK(events == 1 && out.event.code == 200 && out.event.cls == CID_CLASS_SUPERVISORY &&
          out.event.zone == 8 && strcmp(out.event.account, "4321") == 0);
    CHECK(c.state == CALL_KISSOFF && out.tone == TONE_KISSOFF);
    call_tick(&c, KISSOFF_MS, &out);
    CHECK(c.state == CALL_MESSAGE);
    /* A message with a bad checksum gets no kissoff. */
    msg[10] = '9';
    for (const char *k = msg; *k; k++)
        call_digit(&c, *k, &out);
    CHECK(c.state == CALL_MESSAGE && c.bad == 1);
    call_hook(&c, 0, &out);
    CHECK(c.state == CALL_IDLE && out.tone == TONE_NONE);
}

int main(void)
{
    test_zone_decks();
    test_zone_debounce();
    test_line();
    test_dtmf();
    test_contactid();
    test_call();
    if (failures) {
        fprintf(stderr, "%d failures\n", failures);
        return 1;
    }
    puts("all tests passed");
    return 0;
}
