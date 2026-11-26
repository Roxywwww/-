#include "hx711.h"
#include "main.h"

/* Keep each SCK half-period above 0.2 us at the configured 8 MHz clock. */
static void HX711_ClockDelay(void)
{
  volatile uint32_t count;

  for (count = 0U; count < 8U; ++count)
  {
    __NOP();
  }
}

HAL_StatusTypeDef HX711_Read(int32_t *raw, uint32_t timeout_ms)
{
  uint32_t start;
  uint32_t value = 0U;
  uint32_t interrupt_state;
  uint8_t bit_index;

  if (raw == NULL)
  {
    return HAL_ERROR;
  }

  HAL_GPIO_WritePin(HX711_SCK_GPIO_Port, HX711_SCK_Pin, GPIO_PIN_RESET);
  start = HAL_GetTick();
  while (HAL_GPIO_ReadPin(HX711_DOUT_GPIO_Port, HX711_DOUT_Pin) == GPIO_PIN_SET)
  {
    if ((HAL_GetTick() - start) >= timeout_ms)
    {
      return HAL_TIMEOUT;
    }
    HAL_Delay(1U);
  }

  /* An interrupt during SCK high could hold it high long enough to power down
     the HX711. The complete 25-pulse transfer is short, so mask interrupts. */
  interrupt_state = __get_PRIMASK();
  __disable_irq();

  for (bit_index = 0U; bit_index < 24U; ++bit_index)
  {
    HAL_GPIO_WritePin(HX711_SCK_GPIO_Port, HX711_SCK_Pin, GPIO_PIN_SET);
    HX711_ClockDelay();
    value = (value << 1) |
            (HAL_GPIO_ReadPin(HX711_DOUT_GPIO_Port, HX711_DOUT_Pin) == GPIO_PIN_SET ? 1U : 0U);
    HAL_GPIO_WritePin(HX711_SCK_GPIO_Port, HX711_SCK_Pin, GPIO_PIN_RESET);
    HX711_ClockDelay();
  }

  /* Pulse 25 selects channel A with gain 128 for the next conversion. */
  HAL_GPIO_WritePin(HX711_SCK_GPIO_Port, HX711_SCK_Pin, GPIO_PIN_SET);
  HX711_ClockDelay();
  HAL_GPIO_WritePin(HX711_SCK_GPIO_Port, HX711_SCK_Pin, GPIO_PIN_RESET);
  HX711_ClockDelay();

  if (interrupt_state == 0U)
  {
    __enable_irq();
  }

  /* Convert the 24-bit two's-complement result without an unsigned-to-signed
     cast outside the int32_t range. */
  if ((value & 0x800000U) != 0U)
  {
    *raw = (int32_t)value - 0x1000000L;
  }
  else
  {
    *raw = (int32_t)value;
  }

  return HAL_OK;
}
