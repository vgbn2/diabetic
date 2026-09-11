/**
 * @file main.c
 * @brief Bio-Quant STM32 + ESP8266 Telemetry Node Entrypoint
 */

#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include "uart.h"
#include "esp8266.h"

/* SysTick Base */
#define SYSTICK_BASE    0xE000E010
#define SYST_CSR        (*(volatile uint32_t *)(SYSTICK_BASE + 0x00))
#define SYST_RVR        (*(volatile uint32_t *)(SYSTICK_BASE + 0x04))
#define SYST_CVR        (*(volatile uint32_t *)(SYSTICK_BASE + 0x08))

/* GPIOC Base (PC13 LED on Blue Pill) */
#define RCC_BASE        0x40021000
#define RCC_APB2ENR     (*(volatile uint32_t *)(RCC_BASE + 0x18))
#define GPIOC_BASE      0x40011000
#define GPIOC_CRH       (*(volatile uint32_t *)(GPIOC_BASE + 0x04))
#define GPIOC_ODR       (*(volatile uint32_t *)(GPIOC_BASE + 0x0C))

static volatile uint32_t system_millis = 0;

/* SysTick Interrupt Handler - 1ms Tick */
void SysTick_Handler(void) {
    system_millis++;
}

void Delay_ms(uint32_t ms) {
    uint32_t start = system_millis;
    while ((system_millis - start) < ms);
}

void SysTick_Init(void) {
    // 8MHz default clock -> 8000 ticks per ms
    SYST_RVR = 8000 - 1;
    SYST_CVR = 0;
    SYST_CSR = 0x07; // ENABLE, TICKINT, CLKSOURCE = CPU
}

void LED_Init(void) {
    RCC_APB2ENR |= (1U << 4); // IOPCEN
    GPIOC_CRH &= ~(0x0FU << 20); // Clear PC13 config
    GPIOC_CRH |=  (0x02U << 20); // Output 2MHz Push-Pull
    GPIOC_ODR |=  (1U << 13);    // LED Off (PC13 is active-low on Blue Pill)
}

void LED_Toggle(void) {
    GPIOC_ODR ^= (1U << 13);
}

void LED_Set(bool on) {
    if (on) {
        GPIOC_ODR &= ~(1U << 13); // Active LOW
    } else {
        GPIOC_ODR |=  (1U << 13);
    }
}

/* Wi-Fi & Server Config */
#define WIFI_SSID     "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define SERVER_HOST   "192.168.1.100"
#define SERVER_PORT   8000
#define TELEMETRY_URL "/api/v1/telemetry/hardware"

int main(void) {
    SysTick_Init();
    LED_Init();
    UART_Init(115200);

    // Initial LED Blink sequence
    for (int i = 0; i < 6; i++) {
        LED_Toggle();
        Delay_ms(150);
    }

    // Ping ESP8266 AT firmware
    bool esp_ready = false;
    for (int retry = 0; retry < 5; retry++) {
        if (ESP8266_Ping() == ESP8266_OK) {
            esp_ready = true;
            break;
        }
        Delay_ms(500);
    }

    if (esp_ready) {
        ESP8266_Init();
        // Attempt Wi-Fi Connection
        ESP8266_ConnectWiFi(WIFI_SSID, WIFI_PASSWORD, 10000);
    }

    float current_glucose = 5.6f; // mmol/L (~100 mg/dL)
    uint16_t heart_rate = 72;     // BPM

    while (1) {
        LED_Toggle();

        // Format metabolic telemetry JSON payload
        char payload[256];
        snprintf(payload, sizeof(payload),
            "{\"vessel_id\":\"stm32_hw_01\",\"glucose\":%.2f,\"heart_rate\":%u,\"status\":\"NORMAL\"}",
            current_glucose, heart_rate
        );

        char response_buffer[256];
        ESP8266_HTTP_POST(SERVER_HOST, SERVER_PORT, TELEMETRY_URL, payload, response_buffer, sizeof(response_buffer));

        // Simulate biological oscillation
        current_glucose += 0.05f;
        if (current_glucose > 8.0f) current_glucose = 4.8f;

        Delay_ms(5000); // 5-second telemetry interval
    }

    return 0;
}
