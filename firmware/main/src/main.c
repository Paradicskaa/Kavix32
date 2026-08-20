#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/portmacro.h"
#include "driver/uart.h"
#include "driver/gpio.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_chip_info.h"
#include "soc/soc_caps.h"
#include "serial_protocol.h"
#include "usb_hid.h"

static const char *TAG = "MAIN";

#define UART_PORT UART_NUM_0
#define UART_BAUD 460800
#define UART_BUF_SIZE 2048
#define RX_READ_CHUNK 128
#define MOUSE_ACCUM_LIMIT 1024
#define CLIPBOARD_FRAME_MAX_TOTAL (1 + 3 + CLIPBOARD_FRAME_MAX_PAYLOAD + 1)

static portMUX_TYPE hid_state_lock = portMUX_INITIALIZER_UNLOCKED;

static usb_hid_keyboard_report_t keyboard_target_report = {0};
static bool keyboard_target_dirty = false;

static uint8_t mouse_buttons = 0;
static bool mouse_buttons_dirty = false;
static int16_t mouse_dx_accum = 0;
static int16_t mouse_dy_accum = 0;
static int16_t mouse_wheel_accum = 0;
static int16_t mouse_pan_accum = 0;

static void uart_debug_byte(uint8_t value)
{
    uart_write_bytes(UART_PORT, &value, 1);
}

static int16_t clamp_accum_i16(int32_t value)
{
    if (value > MOUSE_ACCUM_LIMIT) {
        return MOUSE_ACCUM_LIMIT;
    }
    if (value < -MOUSE_ACCUM_LIMIT) {
        return -MOUSE_ACCUM_LIMIT;
    }
    return (int16_t)value;
}

static int8_t clamp_i8(int16_t value)
{
    if (value > 127) {
        return 127;
    }
    if (value < -127) {
        return -127;
    }
    return (int8_t)value;
}

typedef struct {
    bool active;
    uint8_t frame[CLIPBOARD_FRAME_MAX_TOTAL];
    size_t frame_len;
    size_t expected_len;
} clipboard_frame_parser_t;

static clipboard_frame_parser_t uart_clipboard_parser = {0};
static clipboard_frame_parser_t cdc_clipboard_parser = {0};

static void clipboard_frame_parser_reset(clipboard_frame_parser_t *parser)
{
    if (!parser) {
        return;
    }
    parser->active = false;
    parser->frame_len = 0;
    parser->expected_len = 0;
}

static bool clipboard_frame_parser_feed(clipboard_frame_parser_t *parser, uint8_t byte,
                                        const uint8_t **frame, size_t *frame_len)
{
    if (!parser || !frame || !frame_len) {
        return false;
    }

    *frame = NULL;
    *frame_len = 0;

    if (!parser->active) {
        if (byte != CLIPBOARD_FRAME_START) {
            return false;
        }
        parser->active = true;
        parser->frame_len = 0;
        parser->expected_len = 0;
    }

    if (parser->frame_len >= sizeof(parser->frame)) {
        clipboard_frame_parser_reset(parser);
        return false;
    }

    parser->frame[parser->frame_len++] = byte;

    if (parser->frame_len == 4) {
        uint16_t payload_len = ((uint16_t)parser->frame[2] << 8) | parser->frame[3];
        if (payload_len > CLIPBOARD_FRAME_MAX_PAYLOAD) {
            clipboard_frame_parser_reset(parser);
            return false;
        }
        parser->expected_len = (size_t)1 + 3 + payload_len + 1;
    }

    if (parser->expected_len != 0 && parser->frame_len == parser->expected_len) {
        uint8_t checksum = serial_protocol_crc8(&parser->frame[1], parser->expected_len - 2);
        bool valid = (parser->frame[1] == CLIPBOARD_FRAME_TYPE_TEXT) &&
                     (parser->frame[parser->expected_len - 1] == checksum);
        if (valid) {
            *frame = parser->frame;
            *frame_len = parser->expected_len;
        }
        clipboard_frame_parser_reset(parser);
        return valid;
    }

    return false;
}

void uart_init(void)
{
    esp_err_t err = uart_driver_install(UART_PORT, UART_BUF_SIZE * 2, 0, 0, NULL, 0);
    if (err == ESP_ERR_INVALID_STATE) {
        ESP_LOGW(TAG, "UART0 driver already installed; reusing existing driver");
    } else {
        ESP_ERROR_CHECK(err);
    }

    const uart_config_t uart_config = {
        .baud_rate = UART_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    ESP_ERROR_CHECK(uart_param_config(UART_PORT, &uart_config));
    ESP_ERROR_CHECK(uart_set_pin(UART_PORT, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    uart_flush_input(UART_PORT);

    ESP_LOGI(TAG, "UART initialized at %d baud", UART_BAUD);
}

void process_packet(const serial_packet_t *pkt)
{
    if (pkt->pkt_type == PKT_TYPE_KEYBOARD) {
        portENTER_CRITICAL(&hid_state_lock);
        if (pkt->data3 == KEY_ACTION_PRESS) {
            keyboard_target_report.modifier = pkt->data2;
            keyboard_target_report.keycode[0] = pkt->data1;
        } else if (pkt->data3 == KEY_ACTION_RELEASE) {
            keyboard_target_report.modifier = pkt->data2;
            if (pkt->data1 == 0 || keyboard_target_report.keycode[0] == pkt->data1) {
                keyboard_target_report.keycode[0] = 0;
            }
        }
        keyboard_target_dirty = true;
        portEXIT_CRITICAL(&hid_state_lock);
        uart_debug_byte(hid_is_connected() ? 0xA1 : 0xE1);
    } else if (pkt->pkt_type == PKT_TYPE_MOUSE_MOVE) {
        int8_t dx = (int8_t)pkt->data2;
        int8_t dy = (int8_t)pkt->data3;
        portENTER_CRITICAL(&hid_state_lock);
        if (mouse_buttons != pkt->data1) {
            mouse_buttons = pkt->data1;
            mouse_buttons_dirty = true;
        }
        mouse_dx_accum = clamp_accum_i16((int32_t)mouse_dx_accum + dx);
        mouse_dy_accum = clamp_accum_i16((int32_t)mouse_dy_accum + dy);
        portEXIT_CRITICAL(&hid_state_lock);
    } else if (pkt->pkt_type == PKT_TYPE_MOUSE_WHEEL) {
        int8_t wheel = (int8_t)pkt->data2;
        int8_t pan = (int8_t)pkt->data3;
        portENTER_CRITICAL(&hid_state_lock);
        if (mouse_buttons != pkt->data1) {
            mouse_buttons = pkt->data1;
            mouse_buttons_dirty = true;
        }
        mouse_wheel_accum = clamp_accum_i16((int32_t)mouse_wheel_accum + wheel);
        mouse_pan_accum = clamp_accum_i16((int32_t)mouse_pan_accum + pan);
        portEXIT_CRITICAL(&hid_state_lock);
    }
}

void hid_tx_task(void *pvParameters)
{
    ESP_LOGI(TAG, "HID TX Task started");

    while (1) {
        if (!hid_is_connected()) {
            vTaskDelay(2 / portTICK_PERIOD_MS);
            continue;
        }

        bool have_keyboard = false;
        usb_hid_keyboard_report_t keyboard_snapshot = {0};

        portENTER_CRITICAL(&hid_state_lock);
        if (keyboard_target_dirty) {
            keyboard_snapshot = keyboard_target_report;
            have_keyboard = true;
        }
        portEXIT_CRITICAL(&hid_state_lock);

        if (have_keyboard && hid_send_keyboard_report(&keyboard_snapshot)) {
            portENTER_CRITICAL(&hid_state_lock);
            if (memcmp(&keyboard_target_report, &keyboard_snapshot, sizeof(usb_hid_keyboard_report_t)) == 0) {
                keyboard_target_dirty = false;
            }
            portEXIT_CRITICAL(&hid_state_lock);
        }

        for (int burst = 0; burst < 8; ++burst) {
            bool sent_any = false;

            bool have_move = false;
            bool move_had_button_dirty = false;
            uint8_t move_buttons = 0;
            int8_t move_dx = 0;
            int8_t move_dy = 0;

            portENTER_CRITICAL(&hid_state_lock);
            if (mouse_dx_accum != 0 || mouse_dy_accum != 0 || mouse_buttons_dirty) {
                move_buttons = mouse_buttons;
                move_dx = clamp_i8(mouse_dx_accum);
                move_dy = clamp_i8(mouse_dy_accum);
                mouse_dx_accum -= move_dx;
                mouse_dy_accum -= move_dy;
                move_had_button_dirty = mouse_buttons_dirty;
                mouse_buttons_dirty = false;
                have_move = true;
            }
            portEXIT_CRITICAL(&hid_state_lock);

            if (have_move) {
                if (!hid_send_mouse_report(move_buttons, move_dx, move_dy, 0, 0)) {
                    portENTER_CRITICAL(&hid_state_lock);
                    mouse_buttons = move_buttons;
                    mouse_dx_accum = clamp_accum_i16((int32_t)mouse_dx_accum + move_dx);
                    mouse_dy_accum = clamp_accum_i16((int32_t)mouse_dy_accum + move_dy);
                    if (move_had_button_dirty) {
                        mouse_buttons_dirty = true;
                    }
                    portEXIT_CRITICAL(&hid_state_lock);
                    break;
                }
                sent_any = true;
            }

            bool have_wheel = false;
            uint8_t wheel_buttons = 0;
            int8_t wheel = 0;
            int8_t pan = 0;

            portENTER_CRITICAL(&hid_state_lock);
            if (mouse_wheel_accum != 0 || mouse_pan_accum != 0) {
                wheel_buttons = mouse_buttons;
                wheel = clamp_i8(mouse_wheel_accum);
                pan = clamp_i8(mouse_pan_accum);
                mouse_wheel_accum -= wheel;
                mouse_pan_accum -= pan;
                have_wheel = true;
            }
            portEXIT_CRITICAL(&hid_state_lock);

            if (have_wheel) {
                if (!hid_send_mouse_report(wheel_buttons, 0, 0, wheel, pan)) {
                    portENTER_CRITICAL(&hid_state_lock);
                    mouse_wheel_accum = clamp_accum_i16((int32_t)mouse_wheel_accum + wheel);
                    mouse_pan_accum = clamp_accum_i16((int32_t)mouse_pan_accum + pan);
                    portEXIT_CRITICAL(&hid_state_lock);
                    break;
                }
                sent_any = true;
            }

            if (!sent_any) {
                break;
            }
        }

        vTaskDelay(1 / portTICK_PERIOD_MS);
    }
}

void uart_rx_task(void *pvParameters)
{
    ESP_LOGI(TAG, "UART RX Task started");
    uint8_t read_chunk[RX_READ_CHUNK];
    uint8_t frame_payload[sizeof(serial_packet_t)] = {0};
    size_t frame_payload_pos = 0;
    bool frame_started = false;
    clipboard_frame_parser_reset(&uart_clipboard_parser);

    while (1) {
        int len = uart_read_bytes(UART_PORT, read_chunk, sizeof(read_chunk), 2 / portTICK_PERIOD_MS);
        if (len <= 0) {
            continue;
        }

        for (int i = 0; i < len; ++i) {
            uint8_t b = read_chunk[i];

            if (!frame_started) {
                if (b == SERIAL_FRAME_START) {
                    frame_started = true;
                    frame_payload_pos = 0;
                }
            } else {
                frame_payload[frame_payload_pos++] = b;
                if (frame_payload_pos == sizeof(serial_packet_t)) {
                    serial_packet_t pkt;
                    memcpy(&pkt, frame_payload, sizeof(serial_packet_t));
                    if (serial_protocol_validate(&pkt)) {
                        process_packet(&pkt);
                    }
                    frame_started = false;
                    frame_payload_pos = 0;
                }
            }

            const uint8_t *clipboard_frame = NULL;
            size_t clipboard_frame_len = 0;
            if (clipboard_frame_parser_feed(&uart_clipboard_parser, b, &clipboard_frame, &clipboard_frame_len)) {
                hid_cdc_write(clipboard_frame, clipboard_frame_len);
            }
        }
    }
}

void cdc_rx_task(void *pvParameters)
{
    ESP_LOGI(TAG, "CDC RX Task started");
    uint8_t read_chunk[RX_READ_CHUNK];
    clipboard_frame_parser_reset(&cdc_clipboard_parser);

    while (1) {
        size_t len = hid_cdc_read(read_chunk, sizeof(read_chunk));
        if (len == 0) {
            vTaskDelay(1 / portTICK_PERIOD_MS);
            continue;
        }

        for (size_t i = 0; i < len; ++i) {
            const uint8_t *clipboard_frame = NULL;
            size_t clipboard_frame_len = 0;
            if (clipboard_frame_parser_feed(&cdc_clipboard_parser, read_chunk[i], &clipboard_frame, &clipboard_frame_len)) {
                uart_write_bytes(UART_PORT, clipboard_frame, clipboard_frame_len);
            }
        }
    }
}

void heartbeat_task(void *pvParameters)
{
    ESP_LOGI(TAG, "Heartbeat Task started");
    int tick = 0;

    while (1) {
        bool mounted = hid_is_connected();
        if ((tick % 10) == 0) {
            uart_debug_byte(mounted ? 0xC1 : 0xC0);
        }

        uart_debug_byte(PKT_TYPE_HEARTBEAT);
        tick++;
        vTaskDelay(100 / portTICK_PERIOD_MS);
    }
}

void app_main(void)
{
    esp_chip_info_t chip_info;
    esp_chip_info(&chip_info);

    ESP_LOGI(TAG, "Kavix32 firmware starting");
    ESP_LOGI(TAG, "Chip: %s, Cores: %d, Features: WiFi=%d BT=%d USB=%d",
             CONFIG_IDF_TARGET, chip_info.cores,
             (chip_info.features & CHIP_FEATURE_WIFI_BGN) ? 1 : 0,
             (chip_info.features & CHIP_FEATURE_BT) ? 1 : 0,
             SOC_USB_OTG_SUPPORTED ? 1 : 0);

    uart_init();
    if (!hid_init()) {
        ESP_LOGE(TAG, "HID init failed");
    }

    xTaskCreatePinnedToCore(uart_rx_task, "uart_rx", 6144, NULL, 10, NULL, 0);
    xTaskCreatePinnedToCore(hid_tx_task, "hid_tx", 4096, NULL, 9, NULL, 1);
    xTaskCreatePinnedToCore(cdc_rx_task, "cdc_rx", 6144, NULL, 8, NULL, 1);
    xTaskCreatePinnedToCore(heartbeat_task, "heartbeat", 2048, NULL, 5, NULL, 1);

    ESP_LOGI(TAG, "Tasks created. Waiting for input...");
}
