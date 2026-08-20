#include <string.h>
#include "usb_hid.h"
#include "esp_log.h"
#include "esp_err.h"
#include "tinyusb.h"
#include "tinyusb_default_config.h"
#include "class/hid/hid_device.h"
#include "class/cdc/cdc_device.h"

static const char *TAG = "USB_HID";
static usb_hid_keyboard_report_t current_report = {0};

#define CDC_ITF_NUM 0
#define CDC_DATA_ITF_NUM 1
#define HID_ITF_NUM 2
#define TUSB_DESC_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN + TUD_HID_DESC_LEN)
#define CDC_EP_NOTIF 0x82
#define CDC_EP_OUT 0x03
#define CDC_EP_IN 0x83
#define HID_EP_ADDR 0x81

static const uint8_t hid_report_descriptor[] = {
    TUD_HID_REPORT_DESC_KEYBOARD(HID_REPORT_ID(HID_REPORT_ID_KEYBOARD)),
    TUD_HID_REPORT_DESC_MOUSE(HID_REPORT_ID(HID_REPORT_ID_MOUSE)),
};

static const uint8_t hid_configuration_descriptor[] = {
    // Configuration descriptor: config number, interface count, string index, total length,
    // attributes, and max power (mA units).
    TUD_CONFIG_DESCRIPTOR(1, 3, 0, TUSB_DESC_TOTAL_LEN, TUSB_DESC_CONFIG_ATT_REMOTE_WAKEUP, 100),

    // CDC ACM descriptor used for clipboard sync software on the Emulation Client PC.
    TUD_CDC_DESCRIPTOR(CDC_ITF_NUM, 0, CDC_EP_NOTIF, 8, CDC_EP_OUT, CDC_EP_IN, 64),

    // HID interface descriptor: interface number, string index, protocol,
    // report descriptor length, endpoint address, endpoint size, polling interval.
    TUD_HID_DESCRIPTOR(HID_ITF_NUM, 0, HID_ITF_PROTOCOL_NONE, sizeof(hid_report_descriptor), HID_EP_ADDR, 16, 1),
};

// Handle GET HID REPORT DESCRIPTOR request.
uint8_t const *tud_hid_descriptor_report_cb(uint8_t instance)
{
    (void)instance;
    return hid_report_descriptor;
}

// Handle GET_REPORT control request.
uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type,
                               uint8_t *buffer, uint16_t reqlen)
{
    (void)instance;
    (void)report_id;
    (void)report_type;
    (void)buffer;
    (void)reqlen;
    return 0;
}

// Handle SET_REPORT control request or OUT endpoint data.
void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type,
                           uint8_t const *buffer, uint16_t bufsize)
{
    (void)instance;
    (void)report_id;
    (void)report_type;
    (void)buffer;
    (void)bufsize;
}

bool hid_init(void)
{
    tinyusb_config_t usb_cfg = TINYUSB_DEFAULT_CONFIG();
    usb_cfg.descriptor.full_speed_config = hid_configuration_descriptor;
#if (TUD_OPT_HIGH_SPEED)
    usb_cfg.descriptor.high_speed_config = hid_configuration_descriptor;
#endif

    esp_err_t err = tinyusb_driver_install(&usb_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "tinyusb_driver_install failed: %s", esp_err_to_name(err));
        return false;
    }
    memset(&current_report, 0, sizeof(current_report));
    ESP_LOGI(TAG, "USB HID initialized");
    return true;
}

bool hid_send_keyboard_report(const usb_hid_keyboard_report_t *report)
{
    if (!tud_hid_ready()) {
        return false;
    }
    return tud_hid_keyboard_report(HID_REPORT_ID_KEYBOARD, report->modifier, report->keycode);
}

bool hid_send_mouse_report(uint8_t buttons, int8_t x, int8_t y, int8_t wheel, int8_t pan)
{
    if (!tud_hid_ready()) {
        return false;
    }
    return tud_hid_mouse_report(HID_REPORT_ID_MOUSE, buttons, x, y, wheel, pan);
}

bool hid_press_key(uint8_t key_code, uint8_t modifiers)
{
    current_report.modifier = modifiers;
    current_report.keycode[0] = key_code;
    return hid_send_keyboard_report(&current_report);
}

bool hid_release_key(uint8_t key_code, uint8_t modifiers)
{
    current_report.modifier = modifiers;
    if (current_report.keycode[0] == key_code) {
        current_report.keycode[0] = 0;
    }
    return hid_send_keyboard_report(&current_report);
}

bool hid_is_connected(void)
{
    return tud_mounted();
}

bool hid_cdc_connected(void)
{
    return tud_cdc_n_connected(0);
}

size_t hid_cdc_read(uint8_t *buffer, size_t max_len)
{
    if (!buffer || max_len == 0) {
        return 0;
    }
    uint32_t available = tud_cdc_n_available(0);
    if (available == 0) {
        return 0;
    }
    if (available > max_len) {
        available = (uint32_t)max_len;
    }
    return tud_cdc_n_read(0, buffer, available);
}

bool hid_cdc_write(const uint8_t *data, size_t len)
{
    if (!data || len == 0) {
        return true;
    }
    if (!tud_mounted()) {
        return false;
    }

    size_t total_written = 0;
    while (total_written < len) {
        uint32_t wrote = tud_cdc_n_write(0, data + total_written, len - total_written);
        if (wrote == 0) {
            break;
        }
        total_written += wrote;
    }
    tud_cdc_n_write_flush(0);
    return total_written == len;
}
