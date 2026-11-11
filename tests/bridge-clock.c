/* SPDX-License-Identifier: GPL-2.0-only
 * Linux port regression checks, Alexander Shmelev (s1mb1o), 2026-11-10.
 */
/* Offline checks of the capture bridge's byte order and PLL flag handling. */
#include "config.h"
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <usb.h>
#include "crusher.h"
#include "mg1264.h"
#include "mg1264-io.h"
#include "mg1264-mware.h"

static uint16_t bridge_register;
static uint16_t writes[4];
static int write_count, reached_loader, force_error, self_clearing_flags;

int usb_control_msg(usb_dev_handle *handle, int type, int request, int value,
                    int index, char *bytes, int size, int timeout)
{
    (void)handle; (void)timeout;
    if (force_error) { errno = EIO; return -EIO; }
    if (request == 0xb9 && type == 0xc0 && index == 0x1a && size == 2) {
        bytes[0] = bridge_register >> 8;
        bytes[1] = bridge_register & 0xff;
        return 2;
    }
    if (request == 0xba && type == 0x40 && size == 0) {
        if (index == 0x1a) {
            if (write_count >= 4) return -EINVAL;
            writes[write_count++] = value;
            bridge_register = value;
            if (self_clearing_flags && write_count == 1)
                bridge_register = 0; /* Readback observed on the user's recorder. */
        }
        return 0;
    }
    if (request == 0xbb || request == 0xbc) return 0;
    if (request == 0xbf && type == 0x40 && size == 1) return 1;
    fprintf(stderr, "Unexpected control request %02x/%02x, index=%04x, size=%d\n",
            type, request, index, size);
    return -EINVAL;
}

int mg1264_load_firmware(crusher_t *crusher, FILE *firmware)
{
    (void)crusher; (void)firmware;
    reached_loader++;
    return 0; /* Stop after bridge/I2C setup; do not emulate running firmware. */
}

int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    crusher_t crusher;
    crusher_defaults(&crusher);
    uint16_t decoded = 0;
    bridge_register = 0x1202;
    int result = mg1264_hbrr(&crusher, 0x1a, &decoded);
    if (result <= 0 || decoded != 0x1202) {
        fprintf(stderr, "Host register byte-order mismatch: %04x instead of 1202\n", decoded);
        return 1;
    }
    force_error = 1;
    decoded = 0xface;
    result = mg1264_hbrr(&crusher, 0x1a, &decoded);
    if (result != 0 || decoded != 0xface) {
        fputs("Failed register read did not report failure/preserve output\n", stderr);
        return 1;
    }
    force_error = 0;
    crusher.devtype = crusher.devmode = DEV_TYPE_CAPTURE;
    mware_defaults(&crusher);
    crusher.mg1264fw = argv[1];
    bridge_register = 0x1202;
    if (crusher_init_device(&crusher) != 0 || reached_loader != 1 || write_count != 2 ||
        writes[0] != 0x1200 || writes[1] != 0x1201) {
        fprintf(stderr, "PLL sequence mismatch: writes=%d, first=%04x, last=%04x, loader=%d\n",
                write_count, writes[0], writes[1], reached_loader);
        return 1;
    }
    write_count = reached_loader = 0;
    self_clearing_flags = 1;
    bridge_register = 0x0200;
    if (crusher_init_device(&crusher) != 0 || reached_loader != 1 || write_count != 2 ||
        writes[0] != 0x0200 || writes[1] != 0x0001) {
        fputs("Bridge sequence does not handle the observed changing register readback\n", stderr);
        return 1;
    }
    crusher_close(&crusher);
    puts("Host register byte order and preserved PLL flags match the Mac sequence.");
    return 0;
}
