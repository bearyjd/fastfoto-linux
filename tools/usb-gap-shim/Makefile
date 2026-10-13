# Builds the FF-680W USB gap shim with gcc (override with `make CC=...`).
CC = gcc
CFLAGS = -O2
WARNINGS = -Wall -Wextra -Werror

all: ff680w_usb_gap.so

ff680w_usb_gap.so: ff680w_usb_gap.c
	$(CC) $(CFLAGS) $(WARNINGS) -shared -fPIC -pthread -o $@ $< -ldl

clean:
	rm -f ff680w_usb_gap.so

.PHONY: all clean
