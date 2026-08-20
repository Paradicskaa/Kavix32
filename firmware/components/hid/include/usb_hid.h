#ifndef USB_HID_H
#define USB_HID_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

typedef struct {
    uint8_t modifier;
    uint8_t reserved;
    uint8_t keycode[6];
} usb_hid_keyboard_report_t;

#define HID_REPORT_ID_KEYBOARD 1
#define HID_REPORT_ID_MOUSE 2

bool hid_init(void);
bool hid_send_keyboard_report(const usb_hid_keyboard_report_t *report);
bool hid_send_mouse_report(uint8_t buttons, int8_t x, int8_t y, int8_t wheel, int8_t pan);
bool hid_press_key(uint8_t key_code, uint8_t modifiers);
bool hid_release_key(uint8_t key_code, uint8_t modifiers);
bool hid_is_connected(void);
bool hid_cdc_connected(void);
size_t hid_cdc_read(uint8_t *buffer, size_t max_len);
bool hid_cdc_write(const uint8_t *data, size_t len);

#endif
