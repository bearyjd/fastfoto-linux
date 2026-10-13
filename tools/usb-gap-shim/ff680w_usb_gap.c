/* LD_PRELOAD shim: FF-680W ignores a bulk OUT that arrives back-to-back with
 * the end of its previous bulk IN reply. Enforce a small gap before OUT. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdlib.h>
#include <time.h>

typedef struct libusb_device_handle libusb_device_handle;
typedef int (*bulk_fn)(libusb_device_handle *, unsigned char, unsigned char *,
                       int, int *, unsigned int);

static struct timespec last_in;
static long gap_us = -1;

static long elapsed_us(const struct timespec *since) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (now.tv_sec - since->tv_sec) * 1000000L +
           (now.tv_nsec - since->tv_nsec) / 1000L;
}

int libusb_bulk_transfer(libusb_device_handle *h, unsigned char ep,
                         unsigned char *data, int len, int *done,
                         unsigned int timeout) {
    static bulk_fn real;
    if (!real) real = (bulk_fn)dlsym(RTLD_NEXT, "libusb_bulk_transfer");
    if (gap_us < 0) {
        const char *env = getenv("FF680W_USB_GAP_US");
        gap_us = env ? atol(env) : 2000;
    }
    if (!(ep & 0x80) && (last_in.tv_sec || last_in.tv_nsec)) {
        long waited = elapsed_us(&last_in);
        if (waited < gap_us) {
            struct timespec ts = {0, (gap_us - waited) * 1000L};
            nanosleep(&ts, NULL);
        }
    }
    int rc = real(h, ep, data, len, done, timeout);
    if (ep & 0x80) clock_gettime(CLOCK_MONOTONIC, &last_in);
    return rc;
}
