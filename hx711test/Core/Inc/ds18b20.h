#ifndef __DS18B20_H
#define __DS18B20_H

#include "stm32f1xx_hal.h"

/* Three-wire mode: VDD=3.3 V, GND=GND, DQ=PA12 with a 4.7 kOhm pull-up. */
void DS18B20_Init(void);
HAL_StatusTypeDef DS18B20_StartConversion(void);
HAL_StatusTypeDef DS18B20_ReadCentiC(int16_t *temperature_centi);

#endif
