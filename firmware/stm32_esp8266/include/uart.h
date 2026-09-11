/**
 * @file uart.h
 * @brief STM32 UART Driver with Ring Buffer support for ESP8266 Communication
 */

#ifndef UART_H
#define UART_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#define UART_RX_BUFFER_SIZE 1024

typedef struct {
    uint8_t buffer[UART_RX_BUFFER_SIZE];
    volatile uint16_t head;
    volatile uint16_t tail;
} RingBuffer;

void UART_Init(uint32_t baudrate);
void UART_PutChar(char c);
void UART_SendString(const char *str);
void UART_SendBuffer(const uint8_t *data, uint16_t length);

bool UART_Available(void);
uint8_t UART_ReadChar(void);
void UART_Flush(void);
uint16_t UART_ReadBytes(uint8_t *out_buf, uint16_t max_len, uint32_t timeout_ms);

#endif /* UART_H */
