/**
 * @file esp8266.c
 * @brief High-Reliability ESP8266 AT Command Driver implementation
 */

#include "esp8266.h"
#include "uart.h"
#include <stdio.h>
#include <string.h>

#define AT_RESP_BUFFER_SIZE 512
static char at_response_buf[AT_RESP_BUFFER_SIZE];

extern void Delay_ms(uint32_t ms);

static bool wait_for_response(const char *expected, uint32_t timeout_ms) {
    uint32_t elapsed = 0;
    uint16_t idx = 0;
    memset(at_response_buf, 0, sizeof(at_response_buf));

    while (elapsed < timeout_ms) {
        while (UART_Available() && idx < (AT_RESP_BUFFER_SIZE - 1)) {
            char c = (char)UART_ReadChar();
            at_response_buf[idx++] = c;
            at_response_buf[idx] = '\0';
            if (strstr(at_response_buf, expected) != NULL) {
                return true;
            }
            if (strstr(at_response_buf, "ERROR") != NULL || strstr(at_response_buf, "FAIL") != NULL) {
                return false;
            }
        }
        Delay_ms(10);
        elapsed += 10;
    }
    return false;
}

ESP8266_Status ESP8266_Ping(void) {
    UART_Flush();
    UART_SendString("AT\r\n");
    if (wait_for_response("OK", 1000)) {
        return ESP8266_OK;
    }
    return ESP8266_TIMEOUT;
}

ESP8266_Status ESP8266_Init(void) {
    // Disable Echo to simplify response parsing
    UART_SendString("ATE0\r\n");
    wait_for_response("OK", 500);

    // Set Station Mode
    return ESP8266_SetModeStation();
}

ESP8266_Status ESP8266_SetModeStation(void) {
    UART_Flush();
    UART_SendString("AT+CWMODE=1\r\n");
    if (wait_for_response("OK", 1000)) {
        return ESP8266_OK;
    }
    return ESP8266_ERROR;
}

ESP8266_Status ESP8266_ConnectWiFi(const char *ssid, const char *password, uint32_t timeout_ms) {
    char cmd[128];
    snprintf(cmd, sizeof(cmd), "AT+CWJAP=\"%s\",\"%s\"\r\n", ssid, password);
    UART_Flush();
    UART_SendString(cmd);

    if (wait_for_response("WIFI CONNECTED", timeout_ms) || wait_for_response("OK", timeout_ms)) {
        return ESP8266_OK;
    }
    return ESP8266_WIFI_DISCONNECTED;
}

ESP8266_Status ESP8266_DisconnectWiFi(void) {
    UART_Flush();
    UART_SendString("AT+CWQAP\r\n");
    if (wait_for_response("OK", 2000)) {
        return ESP8266_OK;
    }
    return ESP8266_ERROR;
}

bool ESP8266_IsConnected(void) {
    UART_Flush();
    UART_SendString("AT+CIPSTATUS\r\n");
    if (wait_for_response("STATUS:2", 1000) || wait_for_response("STATUS:3", 1000) || wait_for_response("STATUS:4", 1000)) {
        return true;
    }
    return false;
}

ESP8266_Status ESP8266_StartTCP(const char *host, uint16_t port) {
    char cmd[128];
    snprintf(cmd, sizeof(cmd), "AT+CIPSTART=\"TCP\",\"%s\",%u\r\n", host, port);
    UART_Flush();
    UART_SendString(cmd);

    if (wait_for_response("CONNECT", 5000) || wait_for_response("OK", 5000)) {
        return ESP8266_OK;
    }
    return ESP8266_TCP_ERROR;
}

ESP8266_Status ESP8266_CloseTCP(void) {
    UART_Flush();
    UART_SendString("AT+CIPCLOSE\r\n");
    wait_for_response("OK", 1000);
    return ESP8266_OK;
}

ESP8266_Status ESP8266_SendPayload(const char *payload, uint16_t length) {
    char cmd[32];
    snprintf(cmd, sizeof(cmd), "AT+CIPSEND=%u\r\n", length);
    UART_Flush();
    UART_SendString(cmd);

    if (!wait_for_response(">", 2000)) {
        return ESP8266_ERROR;
    }

    UART_SendString(payload);
    if (wait_for_response("SEND OK", 5000)) {
        return ESP8266_OK;
    }
    return ESP8266_ERROR;
}

ESP8266_Status ESP8266_HTTP_POST(const char *host, uint16_t port, const char *endpoint, const char *json_body, char *response_out, uint16_t max_resp_len) {
    if (ESP8266_StartTCP(host, port) != ESP8266_OK) {
        return ESP8266_TCP_ERROR;
    }

    char http_packet[1024];
    int packet_len = snprintf(http_packet, sizeof(http_packet),
        "POST %s HTTP/1.1\r\n"
        "Host: %s:%u\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %u\r\n"
        "Connection: close\r\n\r\n"
        "%s",
        endpoint, host, port, (unsigned int)strlen(json_body), json_body);

    if (packet_len < 0 || packet_len >= (int)sizeof(http_packet)) {
        ESP8266_CloseTCP();
        return ESP8266_ERROR;
    }

    ESP8266_Status status = ESP8266_SendPayload(http_packet, (uint16_t)packet_len);
    if (status == ESP8266_OK && response_out != NULL && max_resp_len > 0) {
        // Read response body
        wait_for_response("+IPD", 4000);
        strncpy(response_out, at_response_buf, max_resp_len - 1);
        response_out[max_resp_len - 1] = '\0';
    }

    ESP8266_CloseTCP();
    return status;
}
