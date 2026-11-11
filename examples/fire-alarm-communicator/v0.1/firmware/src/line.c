#include "line.h"

void line_init(line_t *l)
{
    l->offhook = 0;
    l->candidate = 0;
    l->count = 0;
}

int line_feed(line_t *l, uint16_t mv)
{
    int s = mv > LINE_OFFHOOK_MV;
    if (s != l->candidate) {
        l->candidate = s;
        l->count = 1;
    } else if (l->count < LINE_STABLE) {
        l->count++;
    }
    if (l->count >= LINE_STABLE && l->candidate != l->offhook) {
        l->offhook = l->candidate;
        return 1;
    }
    return 0;
}
