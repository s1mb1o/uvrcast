/* SPDX-License-Identifier: GPL-2.0-only
 * Linux port regression checks, Alexander Shmelev (s1mb1o), 2026-11-10.
 */
/* Offline regression checks: never opens or writes a USB device. */
#include "config.h"
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <arpa/inet.h>
#include <usb.h>
#include "crusher.h"
#include "mg1264.h"
#include "mg1264-io.h"

static int reply = -ETIMEDOUT;
static int control_failed;
static uint32_t read_address;
static int memory_reads, memory_reply = -1;

int usb_control_msg(usb_dev_handle *dev, int type, int request, int value,
                    int index, char *bytes, int size, int timeout)
{
    (void)dev; (void)type; (void)value; (void)timeout;
    if (control_failed) { errno = EIO; return -EIO; }
    if (request == 0xbd) {
        assert(size == 9);
        memcpy(&read_address, bytes, 4);
        read_address = ntohl(read_address);
        return size;
    }
    if (request == 0xb9) {
        assert(size == 2);
        bytes[0] = 2; bytes[1] = 1;
        return size;
    }
    assert(size == 1);
    bytes[0] = index == 0x13 ? 0x65 : 0x4f;
    return 1;
}

int usb_bulk_read(usb_dev_handle *dev, int endpoint, char *bytes, int size, int timeout)
{
    (void)dev; (void)timeout;
    if (endpoint == 0x86) {
        memory_reads++;
        if (memory_reply >= 0) return memory_reply;
        memset(bytes, 0, size);
        uint32_t words[11] = {0};
        if (read_address == 0xffc) {
            assert(size == 4); words[0] = 0x400c5080;
        } else if (read_address == 0x400c5080) {
            assert(size == 28); words[4] = 0x400c6000;
        } else if (read_address == 0x400c6000) {
            assert(size == 44);
        } else {
            assert(read_address == 0 && size == 16);
            words[0] = 2; words[3] = 84;
        }
        for (int i = 0; i < size / 4; i++) words[i] = htonl(words[i]);
        memcpy(bytes, words, size);
        return size;
    }
    assert(endpoint == 0x88);
    assert(size == sizeof(event_t));
    if (reply == sizeof(event_t)) {
        event_t event = {0};
        event.eventId = htonl(AVE_EV_READY);
        memcpy(bytes, &event, sizeof(event));
    }
    if (reply < 0) errno = -reply;
    return reply;
}

int main(void)
{
    crusher_t crusher;
    crusher_defaults(&crusher);
    crusher.devmode = DEV_TYPE_CAPTURE;
    crusher.status = 1;
    crusher.out_blocks = 3; /* stale data from a previous event */
    assert(crusher_encode(&crusher, NULL, 0) == CODEC_FLUSHED);
    assert(crusher.out_blocks == 0); /* must not repeat previous frames */
    assert(crusher.event_complete == 1);

    setenv("CRUSHER_DIAGNOSTICS", "1", 1);
    assert(crusher_encode(&crusher, NULL, 0) == CODEC_FLUSHED);
    assert(memory_reads == 4);
    unsetenv("CRUSHER_DIAGNOSTICS");
    uint32_t memory_word = 0;
    memory_reply = 0;
    assert(mg1264_mbr(&crusher, 0xffc, 4, (uint8_t *)&memory_word, 0x40) == 0);
    memory_reply = 2;
    assert(mg1264_mbr(&crusher, 0xffc, 4, (uint8_t *)&memory_word, 0x40) == 0);
    memory_reply = -1;

    reply = sizeof(event_t);
    assert(crusher_encode(&crusher, NULL, 0) == CODEC_FLUSHED);
    assert(((event_t *)crusher.lastEvent)->eventId == AVE_EV_READY);

    reply = -EIO;
    assert(crusher_encode(&crusher, NULL, 0) == CODEC_FAIL);
    reply = 16; /* incomplete event must never be processed */
    assert(crusher_encode(&crusher, NULL, 0) == CODEC_FAIL);
    reply = -ETIMEDOUT;
    control_failed = 1;
    assert(crusher_encode(&crusher, NULL, 0) == CODEC_FAIL);
    control_failed = 0;
    crusher.devmode = DEV_TYPE_ENCODER;
    assert(crusher_encode(&crusher, NULL, 0) == CODEC_FAIL);
    crusher_close(&crusher);
    return 0;
}
