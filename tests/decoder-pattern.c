/* SPDX-License-Identifier: GPL-2.0-only
 * Linux port regression checks, Alexander Shmelev (s1mb1o), 2026-11-10.
 */
/* Offline USB mock: validates test-picture writes, readback, and restoration. */
#include "config.h"
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <usb.h>
#include "crusher.h"
#include "crusher-i2c.h"

static uint8_t luma = 0x36, chroma = 0x7c;
static int fail_read, fail_write, ignore_write, pattern_writes;

int usb_control_msg(usb_dev_handle *dev, int type, int request, int value,
                    int index, char *bytes, int size, int timeout)
{
    (void)dev; (void)timeout;
    assert(request == 0xbf && size == 1);
    if (value != 0x40) {
        assert(!(type & USB_ENDPOINT_IN));
        return 1; /* Other ADC controls are outside this test. */
    }
    if (type & USB_ENDPOINT_IN) {
        assert(index == 0x0c);
        if (fail_read) { errno = EIO; return -EIO; }
        bytes[0] = luma;
        return 1;
    }
    if (index == 0x0c || index == 0x0d) {
        pattern_writes++;
        if (fail_write) return 0; /* Short control transfer. */
        if (!ignore_write) {
            if (index == 0x0c) luma = (uint8_t)bytes[0];
            else chroma = (uint8_t)bytes[0];
        }
    }
    return 1;
}

int main(void)
{
    crusher_t crusher = {0};
    unsetenv("CRUSHER_TEST_PATTERN");
    assert(i2c_init2(&crusher));
    assert(luma == 0x36 && pattern_writes == 0);

    setenv("CRUSHER_TEST_PATTERN", "blue", 1);
    chroma = 0;
    assert(i2c_init2(&crusher));
    assert(luma == 0x37 && chroma == 0x7c && pattern_writes == 2);

    unsetenv("CRUSHER_TEST_PATTERN");
    assert(i2c_init2(&crusher));
    assert(luma == 0x36 && pattern_writes == 3);
    luma = 0xab;
    setenv("CRUSHER_TEST_PATTERN", "off", 1);
    assert(i2c_init2(&crusher));
    assert(luma == 0xaa); /* Preserve all bits except force-enable. */

    setenv("CRUSHER_TEST_PATTERN", "blue", 1);
    luma = 0x36;
    fail_read = 1;
    assert(!i2c_init2(&crusher));
    fail_read = 0;
    fail_write = 1;
    assert(!i2c_init2(&crusher));
    fail_write = 0;
    ignore_write = 1;
    assert(!i2c_init2(&crusher));
    ignore_write = 0;
    setenv("CRUSHER_TEST_PATTERN", "invalid", 1);
    assert(!i2c_init2(&crusher));
    unsetenv("CRUSHER_TEST_PATTERN");
    return 0;
}
