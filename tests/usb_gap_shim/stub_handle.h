/* Fake libusb_device_handle shared by the test stub library and the test driver. */
#ifndef STUB_HANDLE_H
#define STUB_HANDLE_H

struct stub_handle {
    char name[16];
    /* Device identity this handle reports. A negative value means "use the
     * STUB_VID / STUB_PID environment variables (hex), default 04b8 / 016b". */
    long vid;
    long pid;
};

#endif
