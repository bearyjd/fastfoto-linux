/* Stub standing in for libusb-1.0 in the usb-gap-shim tests (no libusb headers needed).
 *
 * Every libusb_bulk_transfer call appends "<handle name> <endpoint hex> <CLOCK_MONOTONIC ns>"
 * to the file named by STUB_LOG. Build with -DSTUB_NO_IDENTITY to leave out
 * libusb_get_device / libusb_get_device_descriptor, or -DSTUB_NO_BULK to leave out
 * libusb_bulk_transfer (simulates a failed symbol lookup in the shim). */
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
int libusb_bulk_transfer(struct stub_handle *h, unsigned char ep, unsigned char *data, int len,
                         int *transferred, unsigned int timeout) {
    (void)data;
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
