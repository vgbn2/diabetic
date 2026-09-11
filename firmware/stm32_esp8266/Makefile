CC = arm-none-eabi-gcc
OBJCOPY = arm-none-eabi-objcopy
SIZE = arm-none-eabi-size

CFLAGS = -mcpu=cortex-m3 -mthumb -Wall -Wextra -O2 -Iinclude -ffreestanding
LDFLAGS = -Tstm32f103.ld -nostartfiles -Wl,--gc-sections --specs=nano.specs -lc -lgcc

BUILD_DIR = build
SRC_DIR = src

SRCS = $(SRC_DIR)/main.c \
       $(SRC_DIR)/uart.c \
       $(SRC_DIR)/esp8266.c \
       $(SRC_DIR)/startup.c

OBJS = $(patsubst $(SRC_DIR)/%.c, $(BUILD_DIR)/%.o, $(SRCS))
TARGET = $(BUILD_DIR)/telemetry_node

all: $(TARGET).bin $(TARGET).hex

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/%.o: $(SRC_DIR)/%.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(TARGET).elf: $(OBJS)
	$(CC) $(CFLAGS) $(LDFLAGS) $(OBJS) -o $@
	$(SIZE) $@

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

$(TARGET).hex: $(TARGET).elf
	$(OBJCOPY) -O ihex $< $@

clean:
	rm -rf $(BUILD_DIR)

flash: $(TARGET).bin
	openocd -f interface/stlink.cfg -f target/stm32f1x.cfg -c "program $(TARGET).bin verify reset exit 0x08000000"

.PHONY: all clean flash
