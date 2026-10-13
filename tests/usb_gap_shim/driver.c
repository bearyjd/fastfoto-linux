/* Test driver: replays a script of libusb calls against the stub library.
 *
 * Each argument is one command:
 *   in:NAME           bulk IN  (endpoint 0x82) on handle NAME
 *   out:NAME          bulk OUT (endpoint 0x01) on handle NAME
 *   sleep:MS          sleep MS milliseconds
 *   close:NAME        libusb_close(handle NAME); the handle keeps its address
 *   open:NAME:VID:PID (re)initialise handle NAME as device VID:PID (hex); same address as before
 * Handles are created on first use with the identity from STUB_VID / STUB_PID. */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "stub_handle.h"

#define MAX_HANDLES 8
#define EP_IN 0x82
#define EP_OUT 0x01

int libusb_bulk_transfer(struct stub_handle *, unsigned char, unsigned char *, int, int *,
                         unsigned int);
void libusb_close(struct stub_handle *);

static struct stub_handle handles[MAX_HANDLES];
static int handle_count;

static struct stub_handle *handle_named(const char *name) {
    for (int i = 0; i < handle_count; i++)
        if (strcmp(handles[i].name, name) == 0) return &handles[i];
    if (handle_count == MAX_HANDLES) {
        fprintf(stderr, "driver: too many handles\n");
        exit(2);
    }
    struct stub_handle *h = &handles[handle_count++];
    snprintf(h->name, sizeof h->name, "%s", name);
    h->vid = h->pid = -1;
    return h;
}

static void run(char *command) {
    char *verb = strtok(command, ":");
    char *name = strtok(NULL, ":");
    unsigned char buf[64] = {0};
    int transferred = 0;

    if (!verb || !name) {
        fprintf(stderr, "driver: bad command\n");
        exit(2);
    }
    if (strcmp(verb, "sleep") == 0) {
        long ms = atol(name);
        struct timespec ts = {ms / 1000, (ms % 1000) * 1000000L};
        nanosleep(&ts, NULL);
    } else if (strcmp(verb, "in") == 0) {
        libusb_bulk_transfer(handle_named(name), EP_IN, buf, sizeof buf, &transferred, 1000);
    } else if (strcmp(verb, "out") == 0) {
        libusb_bulk_transfer(handle_named(name), EP_OUT, buf, sizeof buf, &transferred, 1000);
    } else if (strcmp(verb, "close") == 0) {
        libusb_close(handle_named(name));
    } else if (strcmp(verb, "open") == 0) {
        struct stub_handle *h = handle_named(name);
        const char *vid = strtok(NULL, ":");
        const char *pid = strtok(NULL, ":");
        h->vid = vid ? strtol(vid, NULL, 16) : -1;
        h->pid = pid ? strtol(pid, NULL, 16) : -1;
    } else {
        fprintf(stderr, "driver: unknown command '%s'\n", verb);
        exit(2);
    }
}

int main(int argc, char **argv) {
    for (int i = 1; i < argc; i++) run(argv[i]);
    return 0;
}
