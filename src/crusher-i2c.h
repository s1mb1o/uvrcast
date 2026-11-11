/*
 * Modified 2026-11-09 to 2026-11-10 for the Blackmagic USB Video Recorder
 * Linux port, maintained by Alexander Shmelev (s1mb1o).
 * Original crusher264 author: tipok / piratfm. Original notices retained.
 * This modified version is distributed under GNU GPL v2; see COPYING.GPL.
 */
/*
 * i2c.h
 *
 *  Created on: 13 марта 2010
 *      Author: tipok
 */

#ifndef CRUSHER_I2C_H_
#define CRUSHER_I2C_H_

#include <usb.h>
#include "mg1264.h"
#include "crusher.h"

struct i2c_data {
        uint16_t reg;
        uint8_t val;
} GCC_PACK;

/* sent after startup */
int i2c_init(crusher_t *crusher);
/* sent in the middle of cms sending process */
int i2c_init2(crusher_t *crusher);
int i2c_read_vadc_status(crusher_t *crusher, uint8_t *val);
int i2c_read_vadc_status3(crusher_t *crusher, uint8_t *val);



#endif /* CRUSHER_I2C_H_ */
