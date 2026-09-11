/**
 * @file uart.c
 * @brief STM32F103 bare-metal USART2 ring-buffered driver (PA2: TX, PA3: RX)
 */

#include "uart.h"

/* Peripheral Base Addresses */
#define RCC_BASE        0x40021000
#define GPIOA_BASE      0x40010800
#define USART2_BASE     0x40004400
#define NVIC_BASE       0xE000E100

/* Register Offsets */
#define RCC_APB2ENR     (*(volatile uint32_t *)(RCC_BASE + 0x18))
#define RCC_APB1ENR     (*(volatile uint32_t *)(RCC_BASE + 0x1C))

#define GPIOA_CRL       (*(volatile uint32_t *)(GPIOA_BASE + 0x00))
#define GPIOA_ODR       (*(volatile uint32_t *)(GPIOA_BASE + 0x0C))

#define USART2_SR       (*(volatile uint32_t *)(USART2_BASE + 0x00))
#define USART2_DR       (*(volatile uint32_t *)(USART2_BASE + 0x04))
#define USART2_BRR      (*(volatile uint32_t *)(USART2_BASE + 0x08))
#define USART2_CR1      (*(volatile uint32_t *)(USART2_BASE + 0x0C))

#define NVIC_ISER1      (*(volatile uint32_t *)(NVIC_BASE + 0x04))

#define USART_SR_TXE    (1U << 7)
#define USART_SR_RXNE   (1U << 5)
#define USART_CR1_UE    (1U << 13)
#define USART_CR1_TE    (1U << 3)
#define USART_CR1_RE    (1U << 2)
#define USART_CR1_RXNEIE (1U << 5)

static RingBuffer rx_ring = { .head = 0, .tail = 0 };

extern void Delay_ms(uint32_t ms);

void UART_Init(uint32_t baudrate) {
    // 1. Enable Clocks for GPIOA and USART2
    RCC_APB2ENR |= (1U << 2);  // IOPAEN
    RCC_APB1ENR |= (1U << 17); // USART2EN

    // 2. Configure PA2 as Alternate Function Push-Pull (TX, 50MHz: Mode=11, CNF=10 -> 0xB)
    //    Configure PA3 as Input Floating (RX: Mode=00, CNF=01 -> 0x4)
    GPIOA_CRL &= ~(0xFFU << 8);  // Clear PA2 & PA3 configuration
    GPIOA_CRL |=  (0x4BU << 8);  // PA2: 0xB (AF-PP), PA3: 0x4 (Input Floating)

    // 3. Set Baud Rate (Default 8MHz or 72MHz clock / 36MHz APB1)
    // Assuming 8MHz HSI default clock for APB1: BRR = 8000000 / 115200 = 69.44 -> 0x45
    // If running at 36MHz APB1: BRR = 36000000 / 115200 = 312.5 -> Mantissa=19, Fraction=8 (0x138)
    if (baudrate == 115200) {
        USART2_BRR = 0x0045; // 8MHz APB1 default
    } else {
        USART2_BRR = 8000000 / baudrate;
    }

    // 4. Enable Transmitter, Receiver, and RX Interrupt
    USART2_CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE | USART_CR1_RXNEIE;

    // 5. Enable USART2 Interrupt in NVIC (IRQ 38 -> NVIC_ISER1 bit (38 - 32) = bit 6)
    NVIC_ISER1 |= (1U << 6);
}

void USART2_IRQHandler(void) {
    if (USART2_SR & USART_SR_RXNE) {
        uint8_t data = (uint8_t)(USART2_DR & 0xFF);
        uint16_t next_head = (rx_ring.head + 1) % UART_RX_BUFFER_SIZE;
        if (next_head != rx_ring.tail) {
            rx_ring.buffer[rx_ring.head] = data;
            rx_ring.head = next_head;
        }
    }
}

void UART_PutChar(char c) {
    while (!(USART2_SR & USART_SR_TXE));
    USART2_DR = (uint8_t)c;
}

void UART_SendString(const char *str) {
    while (*str) {
        UART_PutChar(*str++);
    }
}

void UART_SendBuffer(const uint8_t *data, uint16_t length) {
    for (uint16_t i = 0; i < length; i++) {
        UART_PutChar((char)data[i]);
    }
}

bool UART_Available(void) {
    return (rx_ring.head != rx_ring.tail);
}

uint8_t UART_ReadChar(void) {
    if (rx_ring.head == rx_ring.tail) {
        return 0;
    }
    uint8_t data = rx_ring.buffer[rx_ring.tail];
    rx_ring.tail = (rx_ring.tail + 1) % UART_RX_BUFFER_SIZE;
    return data;
}

void UART_Flush(void) {
    rx_ring.tail = rx_ring.head;
}

uint16_t UART_ReadBytes(uint8_t *out_buf, uint16_t max_len, uint32_t timeout_ms) {
    uint16_t count = 0;
    uint32_t elapsed = 0;
    while (count < max_len && elapsed < timeout_ms) {
        if (UART_Available()) {
            out_buf[count++] = UART_ReadChar();
        } else {
            Delay_ms(1);
            elapsed++;
        }
    }
    return count;
}
