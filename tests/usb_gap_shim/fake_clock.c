/* A virtual CLOCK_MONOTONIC for the usb-gap-shim tests, preloaded before the shim.
 *
 * Time stands still until something sleeps: nanosleep() and clock_nanosleep() move it forward by
 * the time asked and return at once. A bulk transfer that "times out after 1000 ms" in the stub
 * thus costs no real time, and the shim's own clock (its 30 s default for finishing a send) can be
 * tested without waiting for it. Other clocks are left alone. Single-threaded use only. */
#define _GNU_SOURCE
#include <errno.h>
#include <stdint.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#define NS_PER_SEC 1000000000LL
#define START_NS (1000LL * NS_PER_SEC) /* an arbitrary, non-zero start */

static long long now_ns = START_NS;

static long long to_ns(const struct timespec *t) {
    return (long long)t->tv_sec * NS_PER_SEC + t->tv_nsec;
}

int clock_gettime(clockid_t id, struct timespec *out) {
    if (id != CLOCK_MONOTONIC) return (int)syscall(SYS_clock_gettime, id, out);
    out->tv_sec = (time_t)(now_ns / NS_PER_SEC);
    out->tv_nsec = (long)(now_ns % NS_PER_SEC);
    return 0;
}

int nanosleep(const struct timespec *request, struct timespec *remaining) {
    (void)remaining;
    now_ns += to_ns(request);
    return 0;
}

int clock_nanosleep(clockid_t id, int flags, const struct timespec *request,
                    struct timespec *remaining) {
    (void)id;
    (void)remaining;
    if (flags & TIMER_ABSTIME) {
        if (to_ns(request) > now_ns) now_ns = to_ns(request);
    } else {
        now_ns += to_ns(request);
    }
    return 0;
}
