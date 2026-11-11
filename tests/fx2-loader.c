/* SPDX-License-Identifier: GPL-2.0-only
 * Linux port regression checks, Alexander Shmelev (s1mb1o), 2026-11-10.
 */
/* Compare every uploaded FX2 byte against an independently decoded HEX image. */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <usb.h>
#include "crusher.h"

static unsigned char actual[65536], written[65536], expected[65536], mask[65536];
static int cpu_held, cpu_started, short_final;

int usb_control_msg(usb_dev_handle *dev, int type, int request, int value,
                    int index, char *bytes, int size, int timeout)
{
    (void)dev; (void)index; (void)timeout;
    if (type != 0x40 || request != 0xa0 || size < 0 || value < 0 || value + size > 65536)
        return -1;
    if (value == 0xe600 && size == 1) {
        if (bytes[0] == 1) cpu_held++;
        if (bytes[0] == 0) cpu_started++;
        return size;
    }
    if (cpu_held != 1 || cpu_started != 0) return -1;
    if (short_final && value == 0x14c4 && size == 12) return size - 1;
    memcpy(actual + value, bytes, size);
    memset(written + value, 1, size);
    return size;
}

static int load_blob(const char *path, unsigned char *bytes)
{
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    int ok = fread(bytes, 1, 65536, f) == 65536;
    fclose(f);
    return ok;
}

static int upload(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    int result = crusher_fx2loader((void *)1, f, 0);
    fclose(f);
    return result;
}

int main(int argc, char **argv)
{
    if (argc != 4 || !load_blob(argv[2], expected) || !load_blob(argv[3], mask)) return 2;
    if (!upload(argv[1])) return 1;
    int failures = 0, compared = 0;
    for (int i = 0; i < 65536; i++) {
        if (!mask[i]) continue;
        compared++;
        if (!written[i] || actual[i] != expected[i]) {
            if (failures < 16) fprintf(stderr, "Missing/incorrect FX2 byte at 0x%04x\n", i);
            failures++;
        }
    }
    if (failures) { fprintf(stderr, "%d firmware bytes missing/incorrect\n", failures); return 1; }
    if (cpu_held != 1 || cpu_started != 1) return 1;

    cpu_held = cpu_started = 0;
    short_final = 1;
    if (upload(argv[1]) != 0 || cpu_started != 0) {
        fputs("Short firmware write was accepted or CPU was started after failure\n", stderr);
        return 1;
    }
    printf("All %d FX2 firmware bytes match; short final writes fail without starting the CPU.\n", compared);
    return 0;
}
