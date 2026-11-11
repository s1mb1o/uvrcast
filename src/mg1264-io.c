/*
 * Modified 2026-11-09 to 2026-11-10 for the Blackmagic USB Video Recorder
 * Linux port, maintained by Alexander Shmelev (s1mb1o).
 * Original crusher264 author: tipok / piratfm. Original notices retained.
 * This modified version is distributed under GNU GPL v2; see COPYING.GPL.
 */
/*
 * io.c
 *
 *  Created on: 10 окт. 2009
 *      Author: tipok
 */

#include <stdint.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <usb.h>

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include "crusher.h"
#include "mg1264.h"
#include "logging.h"
#include "crusher-usb.h"
#include "crusher-i2c.h"
#include "bswap.h"

/*
 * Request 0xb1 reset
 * */
int mg1264_reset_b1(crusher_t *crusher, uint16_t reg)
{
    int ret;
    XTREME("Reset ADC.");

    ret = usb_control_msg((usb_dev_handle *) crusher->udev, USB_TYPE_VENDOR + USB_RECIP_DEVICE,
            EP0_B1_RESET, reg, 0x0000, NULL, 0x0000, USB_TIMEOUT);
    if (ret != 0)
        ERROR("Reset ADC failed.");

    return ret;
}

/*
 * Request 0xbb reset
 * */
int mg1264_reset_bb(crusher_t *crusher, uint16_t reg)
{
    int ret;
    XTREME("Reset ADC.");

    ret = usb_control_msg((usb_dev_handle *) crusher->udev, USB_TYPE_VENDOR + USB_RECIP_DEVICE,
            EP0_BB_RESET, reg, 0x0000, NULL, 0x0000, USB_TIMEOUT);
    if (ret != 0)
        ERROR("Reset ADC failed.");

    return (ret == 0);
}


/*
 * Request 0xbc reset
 * */
int mg1264_reset(crusher_t *crusher)
{
    int ret;
    XTREME("Reset MG1264.");

    ret = usb_control_msg((usb_dev_handle *) crusher->udev, USB_TYPE_VENDOR + USB_RECIP_DEVICE,
                    EP0_RESET, 0x0000, 0x0000, NULL, 0x0000, USB_TIMEOUT);
    if (ret != 0)
        ERROR("Reset MG1264 failed.");

    return (ret == 0);
}

/*
 * host-bus register read 0xb9 implementation
 * */
int mg1264_hbrr(crusher_t *crusher, uint8_t address, uint16_t *data)
{
	uint16_t retval;
	XTREME("Reading host-bus register 0x%02x.", address);

	int ret = usb_control_msg((usb_dev_handle *) crusher->udev, USB_TYPE_VENDOR + USB_RECIP_DEVICE + USB_ENDPOINT_IN,
					EP0_HBRR, 0x00, address, (void *) &retval, sizeof(uint16_t), USB_TIMEOUT);

	if (ret != sizeof(uint16_t)) {
		ERROR("Can't read host-bus register 0x%02x: result=%d", address, ret);
		return 0;
	}

	/* The FX2 returns host-register bytes most significant byte first. */
	*data = be2me_16(retval);
	return 1;
}

/*
 * host-bus register write 0xba implementation
 * */
int mg1264_hbrw(crusher_t *crusher, uint8_t address, uint16_t value)
{
	uint16_t val = value;
	XTREME("Writing host-bus register 0x%02x.", address);
	int ret = usb_control_msg((usb_dev_handle *) crusher->udev, USB_TYPE_VENDOR + USB_RECIP_DEVICE,
								EP0_HBRW, val, address, NULL, 0x00, USB_TIMEOUT);
	if ( ret != 0 )
		ERROR("Cant write host-bus register 0x%02x.", address);
	return (ret == 0);
}


typedef struct csrw_t {
    uint16_t addr;
    uint32_t value;
    uint8_t blockid;
    uint8_t regWidth;
} GCC_PACK csrw_t;

/*
 * codec register write 0xb6 implementation
 * */
int mg1264_csrw(crusher_t *crusher, uint16_t address, uint32_t regval, uint8_t blockid, uint8_t regWidth)
{
	csrw_t data;
	data.addr = me2be_16(address);
	data.value = me2le_32(regval);
	data.blockid = blockid;
	data.regWidth = regWidth;

	int ret = usb_control_msg((usb_dev_handle *) crusher->udev, USB_TYPE_VENDOR + USB_RECIP_DEVICE, EP0_CSRW,
							0x00, 0x00, (void *) &data, sizeof(data), USB_TIMEOUT);
	if ( ret != sizeof(data) ) {
		ERROR("Writing codec register 0x%04x failed.", address);
		dump_bytes((char *) &data, ret);
		return 0;
	}
	return ret;
}


/*
 * codec CSR register read 0xb5 implementation
 * */
int mg1264_csrr(crusher_t *crusher, uint16_t address, uint32_t *value, uint8_t blockid, uint8_t regWidth)
{
	int ret;
	uint16_t addr = address;
	uint16_t in_data = regWidth << 8 | blockid;
	uint32_t val;

	DUMP("Reading codec register 0x%02x.", address);
	ret = usb_control_msg((usb_dev_handle *) crusher->udev, USB_TYPE_VENDOR + USB_RECIP_DEVICE + USB_ENDPOINT_IN,
				EP0_CSRR, in_data, addr, (void *) &val, sizeof(uint32_t), USB_TIMEOUT);

	if (ret != sizeof(uint32_t)){
		ERROR("Reading codec register 0x%04x failed.", address);
		return 0;
	}
	*value = be2me_32(val);
	return ret;
}



typedef struct mb_t {
    uint32_t     addr;
    uint32_t     length;
    uint8_t      partition;
} GCC_PACK mb_t;


/*
 * codec Memory Block write 0xB8->EP2 implementation
 * NOTE: The length of transmitted data must be divisible by 4 without remainder
 *
 * */
int mg1264_mbw (crusher_t *crusher, uint32_t address, uint32_t dataSize, uint8_t *data, uint8_t partition)
{
	uint32_t  sended_bytes = 0;
	uint32_t  to_write;

	uint32_t  sended_pkt_data;
	uint32_t  pktsize;
	int ret;

	mb_t     confpkt;
	confpkt.partition = partition;

#if TEST_MEMBLOCK_SIZE
    if (dataSize % 4) {
    	ERROR("codec Memory Block write: Bad data size %d, must be divesible by 4", dataSize);
    	goto mbw_fail;
    }
#endif

	do {
		if ( dataSize - sended_bytes > MAX_BULK_LEN ) {
			to_write = MAX_BULK_LEN;
		} else {
			to_write = dataSize - sended_bytes;
		}

		confpkt.addr = me2be_32(address + sended_bytes);
		confpkt.length = me2be_32(to_write);
		DUMP("mbw: addr:%08x len:%d:", address + sended_bytes, to_write);
		dump_bytes((char *) &confpkt, sizeof(confpkt));
		ret = usb_control_msg((usb_dev_handle *) crusher->udev, USB_TYPE_VENDOR + USB_RECIP_DEVICE, EP0_MBW,
						0x00, 0x00, (void *) &confpkt, sizeof(confpkt), USB_TIMEOUT);

		if ( ret != sizeof(confpkt) ){
			dump_bytes((char *) &confpkt, sizeof(confpkt));
			ERROR("codec Memory Block write prepare FAILED!"
								" (%d bytes sended from %d).",
								ret, sizeof(confpkt));
			goto mbw_fail;
		}

		sended_pkt_data = 0;
		do {
			if ( to_write - sended_pkt_data > EP_MAX_LEN ) {
				pktsize = EP_MAX_LEN;
			} else {
				pktsize = to_write - sended_pkt_data;
			}

			ret = usb_bulk_write((usb_dev_handle *) crusher->udev, EP2, (void *) data + sended_bytes + sended_pkt_data,
							pktsize, BULK_TOUT);
			if ( ret != pktsize ){
					ERROR("codec Memory Block write FAILED!"
										" (%d bytes sended from %d).",
										ret, pktsize);
					dump_bytes((char *) data + sended_bytes + sended_pkt_data, pktsize);
					goto mbw_fail;
			}

			sended_pkt_data += pktsize;
		} while (to_write > sended_pkt_data);

		sended_bytes += to_write;
	} while (dataSize > sended_bytes);
	return 1;

mbw_fail:
	return 0;
}

/*
 * codec Memory Block read 0xBD->EP6 implementation
 * NOTE: The length of transmitted data must be divisible by 4 without remainder
 * */
int mg1264_mbr (crusher_t *crusher, uint32_t address, uint32_t dataSize, uint8_t *data, uint8_t partition)
{
	uint32_t  readed_bytes = 0;
	uint32_t  to_read;

	uint32_t  readed_pkt_data;
	uint32_t  pktsize;
	int ret;

	mb_t     confpkt;
	confpkt.partition = partition;

#if TEST_MEMBLOCK_SIZE
    if (dataSize % 4) {
    	ERROR("codec Memory Block read: Bad data size %d, must be divesible by 4", dataSize);
    	goto mbr_fail;
    }
#endif

	do {
		if ( dataSize - readed_bytes > MAX_BULK_LEN ) {
			to_read = MAX_BULK_LEN;
		} else {
			to_read = dataSize - readed_bytes;
		}

		confpkt.addr = me2be_32(address + readed_bytes);
		confpkt.length = me2be_32(to_read);
		DUMP("mbr: addr:%08x len:%d:", address + readed_bytes, to_read);
		dump_bytes((char *) &confpkt, sizeof(confpkt));
		ret = usb_control_msg((usb_dev_handle *) crusher->udev, USB_TYPE_VENDOR + USB_RECIP_DEVICE, EP0_MBR,
							0x00, 0x00, (void *) &confpkt, sizeof(confpkt), USB_TIMEOUT);
		if ( ret != sizeof(confpkt) ){
			dump_bytes((char *) &confpkt, sizeof(confpkt));
			ERROR("codec Memory Block read prepare FAILED!"
								" (%d bytes sended from %d).",
								ret, sizeof(confpkt));
			goto mbr_fail;
		}

		readed_pkt_data = 0;
		do {
			if ( to_read - readed_pkt_data > EP_MAX_LEN ) {
				pktsize = EP_MAX_LEN;
			} else {
				pktsize = to_read - readed_pkt_data;
			}

			ret = usb_bulk_read((usb_dev_handle *) crusher->udev, EP6 + USB_ENDPOINT_IN,
								(void *) data + readed_bytes + readed_pkt_data, pktsize, BULK_TOUT);
			if ( ret != pktsize ){
				dump_bytes( (char *)data + readed_bytes + readed_pkt_data, pktsize);
				ERROR("codec Memory Block read FAILED!"
						" (%d bytes readed from %d).", ret, pktsize);
				goto mbr_fail;
			}

			readed_pkt_data += pktsize;
		} while (to_read > readed_pkt_data);
		readed_bytes += to_read;
	} while (dataSize > readed_bytes);
	return readed_bytes;

mbr_fail:
	return 0;
}

/*
 * codec command transfer EP1 implementation
 * */
int mg1264_cmd (crusher_t *crusher, command_t *cmd_in)
{
	int ret, i;
	command_t cmd_out;
	const int pktsize = sizeof(uint32_t)*8;
	cmd_out.controlObjectId = me2be_32(cmd_in->controlObjectId);
	cmd_out.opcode = me2be_32(cmd_in->opcode);
	for (i=0; i<6; i++)
		cmd_out.arguments[i] = me2be_32(cmd_in->arguments[i]);

	DUMP("CMD:");
	dump_bytes( (char *) &cmd_out, pktsize);


	ret = usb_bulk_write((usb_dev_handle *) crusher->udev, EP1, (void *) &cmd_out, pktsize, BULK_TOUT);
	if ( ret != pktsize ){
		ERROR("Cant send data (%d bytes sended from %d).", ret, pktsize);
		dump_bytes( (char *) &cmd_out, pktsize);
		goto cmd_fail;
	}

	ret = usb_bulk_read((usb_dev_handle *) crusher->udev, EP1 + USB_ENDPOINT_IN, (void *) &cmd_out + pktsize,
						pktsize, BULK_TOUT);
	if ( ret != pktsize ){
		ERROR("Can't read data (%d bytes sended from %d).", ret, pktsize);
		dump_bytes( (char *) &cmd_out + pktsize, pktsize);
		goto cmd_fail;
	}

	cmd_in->returnCode = be2me_32(cmd_out.returnCode);
	if (cmd_in->returnCode > 1) {
		DEBUG("Firmware reply: object=%u opcode=%u arg0=%u arg1=%u status=0x%08x",
		      cmd_in->controlObjectId, cmd_in->opcode, cmd_in->arguments[0],
		      cmd_in->arguments[1], cmd_in->returnCode);
	}
	for (i=0; i<7; i++)
		cmd_in->returnValues[i] = be2me_32(cmd_out.returnValues[i]);
	if (getenv("CRUSHER_DIAGNOSTICS") && cmd_in->controlObjectId == AVENCODER_CTRLOBJ_ID
	    && (cmd_in->opcode == CMD_OPCODE_SUBSCRIBE_EVENT || cmd_in->opcode == AVE_CMD_RECORD)) {
		DEBUG("DIAG command opcode=%u reply: %08x %08x %08x %08x %08x %08x %08x %08x",
		      cmd_in->opcode, cmd_in->returnCode, cmd_in->returnValues[0],
		      cmd_in->returnValues[1], cmd_in->returnValues[2], cmd_in->returnValues[3],
		      cmd_in->returnValues[4], cmd_in->returnValues[5], cmd_in->returnValues[6]);
	}
//	return cmd_in->returnCode;
	return 1;

cmd_fail:
	return 0;
}
/*
 * codec event query EP8 implementation
 * */
int mg1264_event (crusher_t *crusher, event_t *event_out)
{
	int ret, i;
	uint8_t v_adc_status = 0;
	event_t event_in;

	if(crusher->devmode == DEV_TYPE_CAPTURE) {
	    if (i2c_read_vadc_status(crusher, &v_adc_status) != 1)
	        return 0;
	    if(crusher->video_adc_status != v_adc_status || getenv("CRUSHER_DIAGNOSTICS")) {
	        crusher->video_adc_status = v_adc_status;

	        DEBUG("Video ADC status 0x%02x: %s%s%s%s%s", v_adc_status,
	                v_adc_status & 0x01 ? "IN_LOCK |" : "",
	                v_adc_status & 0x02 ? "LOST_LOCK_SINCE_LAST_READ |" : "",
	                v_adc_status & 0x04 ? "FSC_LOCK |" : "",
	                v_adc_status & 0x08 ? "FOLLOW_PW |" : "",
	                v_adc_status & 0x80 ? "COL_KILL |" : "");


	        uint8_t status3 = 0;
	        if (i2c_read_vadc_status3(crusher, &status3) == 1) {
	            DEBUG("Video ADC status3 0x%02x: horizontal-lock=%u, field-rate=%s, free-run=%u",
	                  status3, status3 & 1, status3 & 4 ? "50 Hz" : "60 Hz",
	                  (status3 >> 4) & 1);
	        }
	        /* AD_RESULT is not used: i2c_init forces PAL/NTSC rather than auto detection. */
	    }
	}

	ret = usb_bulk_read((usb_dev_handle *) crusher->udev, EP8 + USB_ENDPOINT_IN, (void *) &event_in,
							sizeof(event_t), BULK_TOUT);
	if (ret == -ETIMEDOUT && crusher->devmode == DEV_TYPE_CAPTURE) {
		DEBUG("No codec event within %d ms; waiting for capture data.", BULK_TOUT);
		return -ETIMEDOUT;
	}
	if ( ret != sizeof(event_t) ){
		ERROR("codec event read failed: result=%d, expected=%zu bytes (%s)",
		      ret, sizeof(event_t), ret < 0 ? usb_strerror() : "short transfer");
		goto event_fail;
	}
	event_out->controlObjectId = be2me_32(event_in.controlObjectId);
	event_out->eventId = be2me_32(event_in.eventId);
	event_out->timestamp = be2me_32(event_in.timestamp);

	for (i=0; i<13; i++)
		event_out->payload[i] = be2me_32(event_in.payload[i]);

	XTREME("EVENT: controlObjectId:%d, eventId:%08x, timestamp:%u,\n"
			"payload[0]:%08x, payload[1]:%08x, payload[2]:%08x, payload[3]:%08x, \n"
			"payload[4]:%08x, payload[5]:%08x, payload[6]:%08x, payload[7]:%08x, \n"
			"payload[8]:%08x, payload[9]:%08x, payload[10]:%08x, payload[11]:%08x, \n"
			"payload[12]:%08x\n",
			event_out->controlObjectId, event_out->eventId, event_out->timestamp,
			event_out->payload[0],event_out->payload[1],event_out->payload[2],event_out->payload[3],
			event_out->payload[4],event_out->payload[5],event_out->payload[6],event_out->payload[7],
			event_out->payload[8],event_out->payload[9],event_out->payload[10],event_out->payload[11],
			event_out->payload[12]
	);
	return 1;

event_fail:
	return 0;
}
