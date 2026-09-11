/**
 * @file esp8266.h
 * @brief ESP8266 Wi-Fi AT Command Driver for STM32
 */

#ifndef ESP8266_H
#define ESP8266_H

#include <stdint.h>
#include <stdbool.h>

typedef enum {
    ESP8266_OK = 0,
    ESP8266_ERROR,
    ESP8266_TIMEOUT,
    ESP8266_BUSY,
    ESP8266_WIFI_DISCONNECTED,
    ESP8266_TCP_ERROR
} ESP8266_Status;

typedef struct {
    char ssid[32];
    char password[64];
} ESP8266_WiFiConfig;

typedef struct {
    char host[64];
    uint16_t port;
    bool is_ssl;
} ESP8266_ServerConfig;

/* Initialization & Control */
ESP8266_Status ESP8266_Init(void);
ESP8266_Status ESP8266_HardwareReset(void);
ESP8266_Status ESP8266_Ping(void);

/* Wi-Fi Connectivity */
ESP8266_Status ESP8266_SetModeStation(void);
ESP8266_Status ESP8266_ConnectWiFi(const char *ssid, const char *password, uint32_t timeout_ms);
ESP8266_Status ESP8266_DisconnectWiFi(void);
bool ESP8266_IsConnected(void);

/* HTTP / TCP Operations */
ESP8266_Status ESP8266_StartTCP(const char *host, uint16_t port);
ESP8266_Status ESP8266_CloseTCP(void);
ESP8266_Status ESP8266_SendPayload(const char *payload, uint16_t length);
ESP8266_Status ESP8266_HTTP_POST(const char *host, uint16_t port, const char *endpoint, const char *json_body, char *response_out, uint16_t max_resp_len);

#endif /* ESP8266_H */
