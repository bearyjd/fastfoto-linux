/* Stub standing in for libusb-1.0 in the usb-gap-shim tests (no libusb headers needed).
 *
 * Every libusb_bulk_transfer call appends "<handle name> <endpoint hex> <CLOCK_MONOTONIC ns>"
 * to the file named by STUB_LOG. Build with -DSTUB_NO_IDENTITY to leave out
 * libusb_get_device / libusb_get_device_descriptor, or -DSTUB_NO_BULK to leave out
 * libusb_bulk_transfer (simulates a failed symbol lookup in the shim).
 *
 * STUB_OUT_PLAN / STUB_IN_PLAN script the result of the OUT (IN) calls, one comma-separated entry
 * per call; the last entry repeats. "ok": every byte goes (rc 0). "tN": N bytes go, then the call
 * times out (rc -7) after STUB_TIMEOUT_MS (default 20 ms), as a transfer to a scanner that NAKs.
 * "eC": the call fails with libusb error C and no bytes. Without a plan every call succeeds.
 * If STUB_SENT names a file, the bytes of each OUT call that went are appended to it. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "stub_handle.h"

#define DESCRIPTOR_SIZE 18
#define OFFSET_VENDOR 8
#define OFFSET_PRODUCT 10

#ifndef STUB_NO_BULK
#define LIBUSB_ERROR_TIMEOUT (-7)
#define DEFAULT_TIMEOUT_MS 20
#define MAX_PLAN_BYTES 256

/* The entry of `plan` for call number `call` (from 0): the last entry once they run out. */
static const char *plan_entry(const char *plan, int call, char *buffer, size_t size) {
    char *save = NULL, *entry = NULL;
    snprintf(buffer, size, "%s", plan);
    for (char *token = strtok_r(buffer, ",", &save); token; token = strtok_r(NULL, ",", &save)) {
        entry = token;
        if (call-- == 0) break;
    }
    return entry ? entry : "ok";
}

/* Result of call number `call` under `plan`; sets *transferred. */
static int planned(const char *plan, int call, int len, int *transferred) {
    char buffer[MAX_PLAN_BYTES];
    const char *entry = plan_entry(plan, call, buffer, sizeof buffer);

    if (entry[0] == 'e') {
        *transferred = 0;
        return atoi(entry + 1);
    }
    if (entry[0] == 't') {
        const char *ms = getenv("STUB_TIMEOUT_MS");
        long wait = ms ? atol(ms) : DEFAULT_TIMEOUT_MS;
        struct timespec nap = {wait / 1000, (wait % 1000) * 1000000L};
        int n = atoi(entry + 1);
        nanosleep(&nap, NULL);
        *transferred = n < len ? n : len;
        return LIBUSB_ERROR_TIMEOUT;
    }
    *transferred = len;
    return 0;
}

static void record_sent(const unsigned char *data, int count) {
    const char *path = getenv("STUB_SENT");
    FILE *sent = path ? fopen(path, "ab") : NULL;
    if (!sent) return;
    fwrite(data, 1, (size_t)count, sent);
    fclose(sent);
}

int libusb_bulk_transfer(struct stub_handle *h, unsigned char ep, unsigned char *data, int len,
                         int *transferred, unsigned int timeout) {
    (void)timeout;
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    const char *path = getenv("STUB_LOG");
    FILE *log = path ? fopen(path, "a") : NULL;
    if (!log) {
        fprintf(stderr, "stub: cannot open STUB_LOG\n");
        exit(2);
    }
    fprintf(log, "%s %02x %lld\n", h->name, ep,
            (long long)now.tv_sec * 1000000000LL + now.tv_nsec);
    fclose(log);
    const char *plan = getenv((ep & 0x80) ? "STUB_IN_PLAN" : "STUB_OUT_PLAN");
    if (plan) {
        static int in_calls, out_calls;
        int ignored = 0, rc;
        int *count = (ep & 0x80) ? &in_calls : &out_calls;
        rc = planned(plan, (*count)++, len, transferred ? transferred : &ignored);
        if (!(ep & 0x80)) record_sent(data, transferred ? *transferred : ignored);
        return rc;
    }
    if (transferred) *transferred = len;
    return 0;
}
#endif

void libusb_close(struct stub_handle *h) {
    (void)h;
}

#ifndef STUB_NO_IDENTITY
static long env_hex(const char *name, long fallback) {
    const char *value = getenv(name);
    return value ? strtol(value, NULL, 16) : fallback;
}

struct stub_handle *libusb_get_device(struct stub_handle *h) {
    return h;
}

int libusb_get_device_descriptor(struct stub_handle *dev, unsigned char *desc) {
    uint16_t vid = (uint16_t)(dev->vid >= 0 ? dev->vid : env_hex("STUB_VID", 0x04b8));
    uint16_t pid = (uint16_t)(dev->pid >= 0 ? dev->pid : env_hex("STUB_PID", 0x016b));
    memset(desc, 0, DESCRIPTOR_SIZE);
    desc[0] = DESCRIPTOR_SIZE;
    desc[1] = 1; /* LIBUSB_DT_DEVICE */
    memcpy(desc + OFFSET_VENDOR, &vid, sizeof vid);
    memcpy(desc + OFFSET_PRODUCT, &pid, sizeof pid);
    return 0;
}
#endif
