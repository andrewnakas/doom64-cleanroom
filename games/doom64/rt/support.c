/* Runtime pieces the N64 SDK build got from libkmc / debug libultra. */
#include <ultra64.h>

OSThread __osThreadSave; /* referenced by exceptasm.s; lives in the debug server in libultra */

int abs(int x) { return x < 0 ? -x : x; }

void *memset(void *d, int c, unsigned int n) {
    unsigned char *p = d;
    while (n--) *p++ = (unsigned char)c;
    return d;
}

void *memmove(void *d, const void *s, unsigned int n) {
    unsigned char *p = d;
    const unsigned char *q = s;
    if (p < q) {
        while (n--) *p++ = *q++;
    } else {
        p += n; q += n;
        while (n--) *--p = *--q;
    }
    return d;
}

int memcmp(const void *a, const void *b, unsigned int n) {
    const unsigned char *p = a, *q = b;
    for (; n; n--, p++, q++)
        if (*p != *q) return *p - *q;
    return 0;
}
