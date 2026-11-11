/* SPDX-License-Identifier: GPL-2.0-only
 * Linux port regression checks, Alexander Shmelev (s1mb1o), 2026-11-10.
 */
/* Offline enumeration mock: reload once, re-open after enumeration, clean up. */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <usb.h>
#include "crusher.h"

static struct usb_bus bus;
static struct usb_device device;
struct usb_bus *usb_busses;
static int uploads, opens, closes, upload_ok = 1;

void usb_init(void) {}
int usb_find_busses(void) { return 1; }
int usb_find_devices(void) { return 1; }
usb_dev_handle *usb_open(struct usb_device *dev) { (void)dev; opens++; return (void *)1; }
int usb_close(usb_dev_handle *dev) { (void)dev; closes++; return 0; }
int usb_set_configuration(usb_dev_handle *dev, int n) { (void)dev; (void)n; return 0; }
int usb_claim_interface(usb_dev_handle *dev, int n) { (void)dev; (void)n; return 0; }
int usb_set_altinterface(usb_dev_handle *dev, int n) { (void)dev; (void)n; return 0; }
int usb_reset(usb_dev_handle *dev) { (void)dev; return 0; }
int usb_get_driver_np(usb_dev_handle *dev, int n, char *name, unsigned int len)
{ (void)dev; (void)n; (void)name; (void)len; return -ENODATA; }

int crusher_fx2loader(void *dev, FILE *firmware, int hd)
{
    (void)dev; (void)hd;
    if (fgetc(firmware) != ':') return 0;
    uploads++;
    device.descriptor.idProduct = 0xbd1c;
    return upload_ok;
}

static int scenario(int initialized, int enabled, int success)
{
    memset(&bus, 0, sizeof(bus)); memset(&device, 0, sizeof(device));
    usb_busses = &bus;
    bus.devices = &device; device.bus = &bus;
    device.descriptor.idVendor = 0x04b4;
    device.descriptor.idProduct = initialized ? 0xbd1c : 0x8613;
    uploads = opens = closes = 0; upload_ok = success;
    setenv("CRUSHER_RELOAD_FX2", enabled ? "1" : "0", 1);
    crusher_t crusher;
    crusher_defaults(&crusher);
    int found = crusher_find_device(&crusher, 1);
    int expected_uploads = !initialized || enabled;
    int ok = found == (expected_uploads ? success : 1)
        && uploads == expected_uploads
        && opens == (expected_uploads && success ? 2 : 1);
    crusher_close(&crusher);
    usb_busses = NULL; /* The compatibility library must not free static mock objects. */
    ok = ok && opens == closes;
    if (!ok) fprintf(stderr, "Reload mismatch: found=%d uploads=%d opens=%d closes=%d\n",
                     found, uploads, opens, closes);
    return ok;
}

int main(int argc, char **argv)
{
    if (argc != 2 || chdir(argv[1])) return 2;
    if (!scenario(1, 1, 1) || !scenario(1, 0, 1) || !scenario(1, 1, 0)
        || !scenario(0, 1, 1) || !scenario(0, 1, 0)) return 1;
    puts("FX2 reload occurs once, reopens after enumeration, and cleans up on failure.");
    return 0;
}
