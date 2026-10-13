# Builds the FF-680W USB gap shim with gcc (override with `make CC=...`).
CC = gcc
CFLAGS = -O2
# No -Werror here: a newer compiler's extra warnings must not break a user's build.
WARNINGS = -Wall -Wextra

all: ff680w_usb_gap.so

ff680w_usb_gap.so: ff680w_usb_gap.c
	$(CC) $(CFLAGS) $(WARNINGS) -shared -fPIC -pthread -o $@ $< -ldl

clean:
	rm -f ff680w_usb_gap.so

.PHONY: all clean
