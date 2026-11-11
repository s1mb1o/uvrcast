/* SPDX-License-Identifier: GPL-2.0-only
 * Linux port regression checks, Alexander Shmelev (s1mb1o), 2026-11-10.
 */
/* Validate the real firmware's boot writes with a memory-only USB backend. */
#include "config.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <arpa/inet.h>
#include "crusher.h"
#include "mg1264.h"
#include "mg1264-mware.h"
#include "mg1264-io.h"

static unsigned char header[128];
static unsigned char expected_config[MWARE_SIZE * 4];
static uint32_t selector;
static int saw_selector, saw_config, failed;

int mg1264_mbw(crusher_t *crusher, uint32_t address, uint32_t size,
               uint8_t *bytes, uint8_t partition)
{
    if (address == 0xf00 && partition == 0x40 && size == sizeof(header))
        memcpy(header, bytes, size);
    if (address == crusher->gpb + 0x18 && partition == 0x40 && size == 4) {
        memcpy(&selector, bytes, 4);
        selector = ntohl(selector);
        saw_selector++;
    }
    if (partition == 0x4f) {
        saw_config++;
        if (address != 0 || size != sizeof(expected_config)) {
            fprintf(stderr, "Incorrect product configuration length/address\n");
            failed++;
        } else {
            for (unsigned i = 0; i < size; i++) {
                if (bytes[i] != expected_config[i ^ 3]) {
                    fprintf(stderr, "Product config differs from Mac app at byte %u\n", i);
                    failed++;
                    break;
                }
            }
        }
    }
    return 1;
}

int mg1264_mbr(crusher_t *crusher, uint32_t address, uint32_t size,
               uint8_t *bytes, uint8_t partition)
{
    (void)crusher;
    if (address != 0xf00 || partition != 0x40 || size != sizeof(header))
        return 0;
    memcpy(bytes, header, size);
    return 1;
}

int mg1264_csrr(crusher_t *crusher, uint16_t address, uint32_t *value,
                uint8_t block, uint8_t width)
{
    (void)crusher; (void)address; (void)block; (void)width;
    *value = 0x40;
    return 1;
}

int mg1264_csrw(crusher_t *crusher, uint16_t address, uint32_t value,
                uint8_t block, uint8_t width)
{
    (void)crusher; (void)address; (void)value; (void)block; (void)width;
    return 1;
}

static uint32_t word(unsigned index)
{
    uint32_t value;
    memcpy(&value, header + index * 4, 4);
    return ntohl(value);
}

int main(int argc, char **argv)
{
    if (argc != 3) return 2;
    FILE *config = fopen(argv[2], "rb");
    if (!config || fread(expected_config, 1, sizeof(expected_config), config) != sizeof(expected_config))
        return 2;
    fclose(config);
    FILE *firmware = fopen(argv[1], "rb");
    if (!firmware) return 2;
    crusher_t crusher;
    crusher_defaults(&crusher);
    crusher.devtype = crusher.devmode = DEV_TYPE_CAPTURE;
    mware_defaults(&crusher);
    if (!mg1264_load_firmware(&crusher, firmware)) {
        fprintf(stderr, "Real MG1264 firmware failed memory-only loading\n");
        failed++;
    }
    fclose(firmware);
    if (word(0) != 0x041e || word(1) != 10 || word(11) != 0x0649534e || word(16) != 0xffffffff) {
        fprintf(stderr, "Boot config mismatch: clock/divider=%u, word1=%u, clock=%08x, product=%08x\n",
                word(0), word(1), word(11), word(16));
        failed++;
    }
    if (saw_selector != 1 || selector != 0xffffffff || saw_config != 1) {
        fprintf(stderr, "External product config selector=%08x (expected ffffffff); selector writes=%d, config writes=%d\n",
                selector, saw_selector, saw_config);
        failed++;
    }
    crusher_close(&crusher);
    if (failed) return 1;
    puts("Firmware boot words and product config match the supplied Mac app.");
    return 0;
}
