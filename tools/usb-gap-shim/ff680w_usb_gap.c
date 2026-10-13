/* LD_PRELOAD shim: the Epson FF-680W (04b8:016b) ignores a bulk OUT that arrives back-to-back
 * with the end of its previous bulk IN reply. Enforce a small gap before such an OUT.
 *
 *   FF680W_USB_GAP_US   gap in microseconds (non-negative integer, default 2000, 0 = off)
 *
 * Timestamps are kept per device handle and the gap is only applied to the FF-680W. If the
 * device's VID/PID cannot be looked up (libusb symbols not found, or the call fails) the gap is
 * applied anyway: delaying an OUT by ~2 ms is harmless, missing the delay wedges the scanner.
 * libusb headers are not needed; the 18-byte device descriptor layout is declared locally. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define FF680W_VID 0x04b8
#define FF680W_PID 0x016b
#define DEFAULT_GAP_US 2000L
#define MAX_HANDLES 16
#define ENDPOINT_IN 0x80
#define LIBUSB_ERROR_NOT_FOUND (-5)

struct libusb_device_descriptor {
    uint8_t bLength;
    uint8_t bDescriptorType;
    uint16_t bcdUSB;
    uint8_t bDeviceClass;
    uint8_t bDeviceSubClass;
    uint8_t bDeviceProtocol;
    uint8_t bMaxPacketSize0;
    uint16_t idVendor;
    uint16_t idProduct;
    uint16_t bcdDevice;
    uint8_t iManufacturer;
    uint8_t iProduct;
    uint8_t iSerialNumber;
    uint8_t bNumConfigurations;
};
_Static_assert(sizeof(struct libusb_device_descriptor) == 18, "libusb descriptor layout");

typedef struct libusb_device libusb_device;
typedef struct libusb_device_handle libusb_device_handle;
typedef int (*bulk_fn)(libusb_device_handle *, unsigned char, unsigned char *, int, int *,
                       unsigned int);
typedef void (*close_fn)(libusb_device_handle *);
typedef libusb_device *(*get_device_fn)(libusb_device_handle *);
typedef int (*get_descriptor_fn)(libusb_device *, struct libusb_device_descriptor *);

/* Resolved once by init(). */
static bulk_fn real_bulk;
static close_fn real_close;
static get_device_fn get_device;
static get_descriptor_fn get_descriptor;
static long gap_us = DEFAULT_GAP_US;
static pthread_once_t init_once = PTHREAD_ONCE_INIT;

/* Per-handle state, guarded by table_lock. A handle is identified by its pointer and forgotten
 * in libusb_close(). If more than MAX_HANDLES handles are live at once, the oldest slots are
 * recycled round-robin; an evicted handle simply loses its last-IN time. */
struct slot {
    libusb_device_handle *handle; /* NULL = free */
    int gap_applies;
    int have_in;
    struct timespec last_in;
};
static struct slot table[MAX_HANDLES];
static unsigned next_victim;
static pthread_mutex_t table_lock = PTHREAD_MUTEX_INITIALIZER;

static void *lookup(const char *name) {
    void *symbol = dlsym(RTLD_NEXT, name);
    return symbol ? symbol : dlsym(RTLD_DEFAULT, name);
}

static void init(void) {
    const char *env = getenv("FF680W_USB_GAP_US");
    if (env) {
        char *end;
        long value = strtol(env, &end, 10);
        if (end != env && *end == '\0' && value >= 0) gap_us = value;
    }
    real_bulk = (bulk_fn)dlsym(RTLD_NEXT, "libusb_bulk_transfer");
    real_close = (close_fn)dlsym(RTLD_NEXT, "libusb_close");
    get_device = (get_device_fn)lookup("libusb_get_device");
    get_descriptor = (get_descriptor_fn)lookup("libusb_get_device_descriptor");
}

static int gap_applies_to(libusb_device_handle *h) {
    struct libusb_device_descriptor desc;
    libusb_device *dev = get_device && get_descriptor ? get_device(h) : NULL;
    if (!dev || get_descriptor(dev, &desc) != 0) return 1; /* fail-safe, see header */
    return desc.idVendor == FF680W_VID && desc.idProduct == FF680W_PID;
}

/* Caller holds table_lock. Returns the slot for h, creating it (and resolving the device's
 * VID/PID, once) if needed. */
static struct slot *slot_for(libusb_device_handle *h) {
    struct slot *free_slot = NULL;
    for (int i = 0; i < MAX_HANDLES; i++) {
        if (table[i].handle == h) return &table[i];
        if (!table[i].handle && !free_slot) free_slot = &table[i];
    }
    struct slot *s = free_slot ? free_slot : &table[next_victim++ % MAX_HANDLES];
    memset(s, 0, sizeof *s);
    s->handle = h;
    s->gap_applies = gap_applies_to(h);
    return s;
}

static struct timespec add_us(struct timespec t, long us) {
    t.tv_sec += us / 1000000L;
    t.tv_nsec += (us % 1000000L) * 1000L;
    if (t.tv_nsec >= 1000000000L) {
        t.tv_sec += 1;
        t.tv_nsec -= 1000000000L;
    }
    return t;
}

static void sleep_until(const struct timespec *deadline) {
    while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, deadline, NULL) == EINTR) {
    }
}

int libusb_bulk_transfer(libusb_device_handle *h, unsigned char ep, unsigned char *data, int len,
                         int *done, unsigned int timeout) {
    int is_in = (ep & ENDPOINT_IN) != 0;
    struct timespec deadline = {0, 0};
    int must_wait = 0;

    pthread_once(&init_once, init);
    if (!real_bulk) return LIBUSB_ERROR_NOT_FOUND;

    if (!is_in && gap_us > 0) {
        pthread_mutex_lock(&table_lock);
        struct slot *s = slot_for(h);
        if (s->gap_applies && s->have_in) {
            deadline = add_us(s->last_in, gap_us);
            must_wait = 1;
        }
        pthread_mutex_unlock(&table_lock);
    }
    if (must_wait) sleep_until(&deadline);

    int rc = real_bulk(h, ep, data, len, done, timeout);

    if (is_in) {
        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);
        pthread_mutex_lock(&table_lock);
        struct slot *s = slot_for(h);
        s->last_in = now;
        s->have_in = 1;
        pthread_mutex_unlock(&table_lock);
    }
    return rc;
}

/* Forget a handle before it is closed so a device opened later at the same address is not
 * mistaken for it. */
void libusb_close(libusb_device_handle *h) {
    pthread_once(&init_once, init);
    pthread_mutex_lock(&table_lock);
    for (int i = 0; i < MAX_HANDLES; i++)
        if (table[i].handle == h) memset(&table[i], 0, sizeof table[i]);
    pthread_mutex_unlock(&table_lock);
    if (real_close) real_close(h);
}
