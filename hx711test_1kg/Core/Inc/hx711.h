#ifndef HX711_H
#define HX711_H

#include <stdint.h>
#include "stm32f1xx_hal.h"

/* Read one channel A, gain 128 conversion. HAL_TIMEOUT means DOUT stayed high. */
HAL_StatusTypeDef HX711_Read(int32_t *raw, uint32_t timeout_ms);

#endif /* HX711_H */
