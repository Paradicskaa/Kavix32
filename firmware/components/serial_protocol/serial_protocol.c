#include "serial_protocol.h"
#include <stddef.h>

uint8_t serial_protocol_crc8(const uint8_t *data, size_t len)
{
    uint8_t crc = 0x00;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int j = 0; j < 8; j++) {
            if (crc & 0x80) {
                crc = (crc << 1) ^ 0x07;
            } else {
                crc = crc << 1;
            }
            crc &= 0xFF;
        }
    }
    return crc;
}

bool serial_protocol_validate(const serial_packet_t *pkt)
{
    uint8_t expected_crc = serial_protocol_crc8((uint8_t *)pkt, 4);
    return pkt->checksum == expected_crc;
}

void serial_protocol_encode_keyboard(serial_packet_t *pkt, uint8_t key_code, uint8_t modifiers, key_action_t action)
{
    pkt->pkt_type = PKT_TYPE_KEYBOARD;
    pkt->data1 = key_code;
    pkt->data2 = modifiers;
    pkt->data3 = action;
    pkt->checksum = serial_protocol_crc8((uint8_t *)pkt, 4);
}

void serial_protocol_encode_mouse_move(serial_packet_t *pkt, uint8_t buttons, int8_t delta_x, int8_t delta_y)
{
    pkt->pkt_type = PKT_TYPE_MOUSE_MOVE;
    pkt->data1 = buttons;
    pkt->data2 = (uint8_t)delta_x;
    pkt->data3 = (uint8_t)delta_y;
    pkt->checksum = serial_protocol_crc8((uint8_t *)pkt, 4);
}

void serial_protocol_encode_mouse_wheel(serial_packet_t *pkt, uint8_t buttons, int8_t wheel, int8_t pan)
{
    pkt->pkt_type = PKT_TYPE_MOUSE_WHEEL;
    pkt->data1 = buttons;
    pkt->data2 = (uint8_t)wheel;
    pkt->data3 = (uint8_t)pan;
    pkt->checksum = serial_protocol_crc8((uint8_t *)pkt, 4);
}
