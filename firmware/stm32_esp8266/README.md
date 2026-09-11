# STM32 + ESP8266 (ESP-01/12) Hardware Setup & Firmware Guide

This directory contains the embedded firmware and driver layer for connecting an **STM32F103 (Blue Pill / Nucleo)** microcontroller with an **ESP8266** Wi-Fi module to stream telemetry (glucose, heart rate, sensor data) to the Bio-Quant backend or Nightscout server.

---

## 1. Hardware Pinout & Wiring Diagram

### A. ST-LINK/V2 to STM32F103 (SWD Programming)
| ST-LINK Pin | STM32 Pin | Function |
| :--- | :--- | :--- |
| **3.3V** | 3.3V | Target Power |
| **GND** | GND | Common Ground |
| **SWDIO** | PA13 | SWD Data Line |
| **SWCLK** | PA14 | SWD Clock Line |

---

### B. STM32F103 to ESP8266 (ESP-01 / ESP-12)
> [!IMPORTANT]
> **Power Advisory:** The ESP8266 can draw peak currents up to **250–300 mA** during Wi-Fi transmission bursts (RF calibration / transmit). The 3.3V output from an ST-Link or cheap STM32 onboard LDO cannot supply this and will cause spontaneous brownout resets (`rst cause: 2` or `4`).
> **Power the ESP8266 from an external 3.3V regulator (e.g. AMS1117-3.3V, min 500mA) sharing a common ground (GND) with STM32.**

| ESP8266 Pin | STM32 Pin / Power | Description |
| :--- | :--- | :--- |
| **VCC (3.3V)** | External 3.3V (>=500mA) | **DO NOT use 5V! 3.3V Only** |
| **GND** | STM32 GND + Power GND | Common Ground Reference |
| **TXD** (GPIO1) | **PA3** (USART2 RX) | ESP8266 Transmit -> STM32 Receive |
| **RXD** (GPIO3) | **PA2** (USART2 TX) | STM32 Transmit -> ESP8266 Receive |
| **CH_PD / EN** | **3.3V** (Pull-up via 10kΩ or direct 3.3V) | Chip Enable (Must be HIGH to run) |
| **RST** | **PB0** (or pull-up to 3.3V) | Active-Low Reset (STM32 hardware reset pin) |
| **GPIO0** | **3.3V** (Pull-up via 10kΩ) | High for Flash boot / Normal Run mode |
| **GPIO15** (ESP-12) | **GND** (Pull-down via 10kΩ) | Must be LOW for boot |
| **GPIO2** | **3.3V** (Pull-up via 10kΩ) | Must be HIGH for boot |

---

## 2. ESP8266 AT Command Firmware Verification

The STM32 driver communicates with the ESP8266 using standard Espressif AT firmware at `115200` baud.

To test/verify your ESP8266 module directly using a USB-TTL adapter or esptool:
```bash
# Check ESP8266 chip connection
esptool --port /dev/ttyUSB0 flash_id

# Erase flash (if reflashing fresh AT firmware)
esptool --port /dev/ttyUSB0 erase_flash
```

Default AT commands used by this driver:
- `AT`: Ping device -> `OK`
- `ATE0`: Disable echo
- `AT+CWMODE=1`: Set Station Mode
- `AT+CWJAP="SSID","PASSWORD"`: Connect to Wi-Fi
- `AT+CIPSTART="TCP","host",port`: Open TCP socket
- `AT+CIPSEND=len`: Send data buffer
- `AT+CIPCLOSE`: Close connection

---

## 3. Flashing STM32 with OpenOCD

Your ST-LINK/V2 and STM32F103 Cortex-M3 (128 KB Flash) are detected on the system.

Flash target using OpenOCD:
```bash
openocd -f interface/stlink.cfg -f target/stm32f1x.cfg -c "program build/telemetry_node.bin verify reset exit 0x08000000"
```
