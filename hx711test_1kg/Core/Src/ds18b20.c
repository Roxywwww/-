#include "ds18b20.h"
#include "main.h"

static uint32_t cycles_per_us;

static void DS18B20_DelayUs(uint32_t microseconds)
{
  uint32_t start = DWT->CYCCNT;
  uint32_t cycles = microseconds * cycles_per_us;
  while ((uint32_t)(DWT->CYCCNT - start) < cycles)
  {
  }
}

static void DS18B20_Low(void)
{
  DS18B20_DQ_GPIO_Port->BSRR = (uint32_t)DS18B20_DQ_Pin << 16U;
}

static void DS18B20_Release(void)
{
  DS18B20_DQ_GPIO_Port->BSRR = DS18B20_DQ_Pin;
}

static uint8_t DS18B20_Sample(void)
{
  return (DS18B20_DQ_GPIO_Port->IDR & DS18B20_DQ_Pin) != 0U;
}

/* Mask interrupts only around timing-sensitive 1-Wire slots. */
static uint32_t DS18B20_Lock(void)
{
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  return primask;
}

static void DS18B20_Unlock(uint32_t primask)
{
  __set_PRIMASK(primask);
}

static HAL_StatusTypeDef DS18B20_Reset(void)
{
  uint32_t primask;
  uint8_t present;

  DS18B20_Release();
  if (DS18B20_Sample() == 0U)
  {
    return HAL_ERROR; /* DQ stuck low, e.g. short or wrong wiring. */
  }

  primask = DS18B20_Lock();
  DS18B20_Low();
  DS18B20_DelayUs(480U);
  DS18B20_Release();
  DS18B20_DelayUs(70U);
  present = (uint8_t)(DS18B20_Sample() == 0U);
  DS18B20_Unlock(primask);
  DS18B20_DelayUs(410U);

  return (present != 0U) ? HAL_OK : HAL_ERROR;
}

static void DS18B20_WriteBit(uint8_t bit)
{
  uint32_t primask = DS18B20_Lock();
  DS18B20_Low();
  if (bit != 0U)
  {
    DS18B20_DelayUs(6U);
    DS18B20_Release();
    DS18B20_DelayUs(64U);
  }
  else
  {
    DS18B20_DelayUs(60U);
    DS18B20_Release();
    DS18B20_DelayUs(10U);
  }
  DS18B20_Unlock(primask);
}

static uint8_t DS18B20_ReadBit(void)
{
  uint32_t primask = DS18B20_Lock();
  uint8_t bit;
  DS18B20_Low();
  DS18B20_DelayUs(3U);
  DS18B20_Release();
  DS18B20_DelayUs(10U);
  bit = DS18B20_Sample();
  DS18B20_DelayUs(55U);
  DS18B20_Unlock(primask);
  return bit;
}

static void DS18B20_WriteByte(uint8_t value)
{
  uint8_t i;
  for (i = 0U; i < 8U; ++i)
  {
    DS18B20_WriteBit((uint8_t)(value & 1U));
    value >>= 1U;
  }
}

static uint8_t DS18B20_ReadByte(void)
{
  uint8_t i;
  uint8_t value = 0U;
  for (i = 0U; i < 8U; ++i)
  {
    value |= (uint8_t)(DS18B20_ReadBit() << i);
  }
  return value;
}

static uint8_t DS18B20_Crc8(const uint8_t *data, uint8_t length)
{
  uint8_t crc = 0U;
  uint8_t i;
  uint8_t j;
  for (i = 0U; i < length; ++i)
  {
    uint8_t value = data[i];
    for (j = 0U; j < 8U; ++j)
    {
      uint8_t mix = (uint8_t)((crc ^ value) & 1U);
      crc >>= 1U;
      if (mix != 0U)
      {
        crc ^= 0x8CU;
      }
      value >>= 1U;
    }
  }
  return crc;
}

void DS18B20_Init(void)
{
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0U;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
  cycles_per_us = HAL_RCC_GetHCLKFreq() / 1000000U;
  DS18B20_Release();
}

HAL_StatusTypeDef DS18B20_StartConversion(void)
{
  if (DS18B20_Reset() != HAL_OK)
  {
    return HAL_ERROR;
  }
  DS18B20_WriteByte(0xCCU); /* SKIP ROM: exactly one sensor on DQ. */
  DS18B20_WriteByte(0x44U); /* CONVERT T; returns immediately. */
  return HAL_OK;
}

HAL_StatusTypeDef DS18B20_ReadCentiC(int16_t *temperature_centi)
{
  uint8_t scratchpad[9];
  uint8_t i;
  int16_t raw;

  if (temperature_centi == 0 || DS18B20_Reset() != HAL_OK)
  {
    return HAL_ERROR;
  }
  DS18B20_WriteByte(0xCCU); /* SKIP ROM. */
  DS18B20_WriteByte(0xBEU); /* READ SCRATCHPAD. */
  for (i = 0U; i < 9U; ++i)
  {
    scratchpad[i] = DS18B20_ReadByte();
  }
  if (DS18B20_Crc8(scratchpad, 8U) != scratchpad[8])
  {
    return HAL_ERROR;
  }

  raw = (int16_t)((uint16_t)scratchpad[0] |
                  ((uint16_t)scratchpad[1] << 8U));
  if (raw < (-55 * 16) || raw > (125 * 16))
  {
    return HAL_ERROR;
  }
  *temperature_centi = (int16_t)(((int32_t)raw * 100) / 16);
  return HAL_OK;
}
