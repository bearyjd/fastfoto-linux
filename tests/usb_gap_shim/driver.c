/* Test driver: replays a script of libusb calls against the stub library.
 *
 * Each argument is one command:
 *   in:NAME           bulk IN  (endpoint 0x82) on handle NAME; prints "NAME ep=82 rc=<rc>"
 *   out:NAME          bulk OUT (endpoint 0x01) on handle NAME; prints "NAME ep=01 rc=<rc>"
 *   sleep:MS          sleep MS milliseconds
 *   close:NAME        libusb_close(handle NAME); the handle keeps its address
 *   open:NAME:VID:PID (re)initialise handle NAME as device VID:PID (hex); same address as before
 *   threads:N:M       N threads, each on its own handle (T0..), doing M x (IN then OUT)
 * Handles are created on first use with the identity from STUB_VID / STUB_PID. */
#define _GNU_SOURCE
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "stub_handle.h"

#define MAX_HANDLES 32
#define MAX_THREADS 16
#define EP_IN 0x82
#define EP_OUT 0x01

int libusb_bulk_transfer(struct stub_handle *, unsigned char, unsigned char *, int, int *,
                         unsigned int);
void libusb_close(struct stub_handle *);

static struct stub_handle handles[MAX_HANDLES];
static int handle_count;
static int thread_iterations;

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

static int bulk(struct stub_handle *h, unsigned char ep) {
    unsigned char buf[64] = {0};
    int transferred = 0;
    return libusb_bulk_transfer(h, ep, buf, sizeof buf, &transferred, 1000);
}

static void *thread_main(void *arg) {
    for (int i = 0; i < thread_iterations; i++) {
        bulk(arg, EP_IN);
        bulk(arg, EP_OUT);
    }
    return NULL;
}

static void run_threads(int count, int iterations) {
    pthread_t threads[MAX_THREADS];
    char name[16];

    if (count < 1 || count > MAX_THREADS) {
        fprintf(stderr, "driver: bad thread count\n");
        exit(2);
    }
    thread_iterations = iterations;
    for (int i = 0; i < count; i++) {
        snprintf(name, sizeof name, "T%d", i);
        if (pthread_create(&threads[i], NULL, thread_main, handle_named(name)) != 0) {
            fprintf(stderr, "driver: pthread_create failed\n");
            exit(2);
        }
    }
    for (int i = 0; i < count; i++) pthread_join(threads[i], NULL);
}

static void run(char *command) {
    char *verb = strtok(command, ":");
    char *name = strtok(NULL, ":");

    if (!verb || !name) {
        fprintf(stderr, "driver: bad command\n");
        exit(2);
    }
    if (strcmp(verb, "sleep") == 0) {
        long ms = atol(name);
        struct timespec ts = {ms / 1000, (ms % 1000) * 1000000L};
        nanosleep(&ts, NULL);
    } else if (strcmp(verb, "in") == 0) {
        printf("%s ep=%02x rc=%d\n", name, EP_IN, bulk(handle_named(name), EP_IN));
    } else if (strcmp(verb, "out") == 0) {
        printf("%s ep=%02x rc=%d\n", name, EP_OUT, bulk(handle_named(name), EP_OUT));
    } else if (strcmp(verb, "close") == 0) {
        libusb_close(handle_named(name));
    } else if (strcmp(verb, "open") == 0) {
        struct stub_handle *h = handle_named(name);
        const char *vid = strtok(NULL, ":");
        const char *pid = strtok(NULL, ":");
        h->vid = vid ? strtol(vid, NULL, 16) : -1;
        h->pid = pid ? strtol(pid, NULL, 16) : -1;
    } else if (strcmp(verb, "threads") == 0) {
        const char *iterations = strtok(NULL, ":");
        run_threads(atoi(name), iterations ? atoi(iterations) : 1);
    } else {
        fprintf(stderr, "driver: unknown command '%s'\n", verb);
        exit(2);
    }
}

int main(int argc, char **argv) {
    for (int i = 1; i < argc; i++) run(argv[i]);
    return 0;
}
