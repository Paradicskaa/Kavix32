#ifndef SERIAL_PROTOCOL_H
#define SERIAL_PROTOCOL_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

typedef struct {
    uint8_t pkt_type;
    uint8_t data1;
    uint8_t data2;
    uint8_t data3;
    uint8_t checksum;
} serial_packet_t;

#define SERIAL_FRAME_START 0x7E
#define SERIAL_PAYLOAD_SIZE ((uint8_t)sizeof(serial_packet_t))
#define SERIAL_FRAME_SIZE ((uint8_t)(1 + sizeof(serial_packet_t)))
#define CLIPBOARD_FRAME_START 0x7D
#define CLIPBOARD_FRAME_TYPE_TEXT 0x01
#define CLIPBOARD_FRAME_MAX_PAYLOAD 4096

typedef enum {
    PKT_TYPE_KEYBOARD = 0x01,
    PKT_TYPE_MOUSE_MOVE = 0x02,
    PKT_TYPE_MOUSE_WHEEL = 0x03,
    PKT_TYPE_HEARTBEAT = 0xFF
} packet_type_t;

typedef enum {
    KEY_ACTION_RELEASE = 0x00,
    KEY_ACTION_PRESS = 0x01
} key_action_t;

typedef enum {
    MOD_LEFT_CTRL  = 0x01,
    MOD_LEFT_SHIFT = 0x02,
    MOD_LEFT_ALT   = 0x04,
    MOD_LEFT_GUI   = 0x08,
    MOD_RIGHT_CTRL = 0x10,
    MOD_RIGHT_SHIFT = 0x20,
    MOD_RIGHT_ALT  = 0x40,
    MOD_RIGHT_GUI  = 0x80
} modifier_key_t;

uint8_t serial_protocol_crc8(const uint8_t *data, size_t len);
bool serial_protocol_validate(const serial_packet_t *pkt);
void serial_protocol_encode_keyboard(serial_packet_t *pkt, uint8_t key_code, uint8_t modifiers, key_action_t action);
void serial_protocol_encode_mouse_move(serial_packet_t *pkt, uint8_t buttons, int8_t delta_x, int8_t delta_y);
void serial_protocol_encode_mouse_wheel(serial_packet_t *pkt, uint8_t buttons, int8_t wheel, int8_t pan);

#endif
