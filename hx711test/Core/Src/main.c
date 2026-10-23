/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdio.h>
#include "hx711.h"
#include "oled.h"
#include "ds18b20.h"

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define HX711_TARE_SAMPLES 16U
#define TARE_BUTTON_DEBOUNCE_MS 30U
#define RAW_REPORT_INTERVAL_MS 200U
#define HX711_AVERAGE_SAMPLES 5U
#define OLED_REPORT_INTERVAL_MS 500U
#define DS18B20_CONVERSION_MS 800U
#define DS18B20_RETRY_MS 1000U
/* 500 g calibration on 2026-10-15: 177.6184 ADC counts per gram. */
#define HX711_COUNTS_PER_GRAM_X10000 1776184LL

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
UART_HandleTypeDef huart1;

/* USER CODE BEGIN PV */
static const uint8_t startup_message[] = "USART1 OK, 115200 8N1\r\n";
static int32_t tare_offset;
static uint8_t tare_valid;
static int32_t average_samples[HX711_AVERAGE_SAMPLES];
static int64_t average_sum;
static uint8_t average_count;
static uint8_t average_index;
static uint32_t last_oled_tick;
static uint32_t temperature_tick;
static uint8_t temperature_converting;

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART1_UART_Init(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
static HAL_StatusTypeDef HX711_Tare(int32_t *new_offset)
{
  int64_t sum = 0;
  uint8_t count;
  int32_t sample;
  HAL_StatusTypeDef status;

  for (count = 0U; count < HX711_TARE_SAMPLES; ++count)
  {
    status = HX711_Read(&sample, 200U);
    if (status != HAL_OK)
    {
      return status;
    }
    if (sample == -8388608L || sample == 8388607L)
    {
      return HAL_ERROR;
    }
    sum += sample;
  }

  *new_offset = (int32_t)(sum / HX711_TARE_SAMPLES);
  return HAL_OK;
}

/* Return weight in 0.1 g units; round signed values symmetrically.
   The 64-bit product avoids overflow at the HX711's 24-bit limits. */
static int32_t HX711_NetToTenthsOfGram(int32_t net)
{
  int64_t magnitude = (net < 0) ? -(int64_t)net : (int64_t)net;
  int32_t tenths = (int32_t)((magnitude * 100000LL +
                              HX711_COUNTS_PER_GRAM_X10000 / 2LL) /
                             HX711_COUNTS_PER_GRAM_X10000);

  return (net < 0) ? -tenths : tenths;
}

static void HX711_AverageReset(void)
{
  average_sum = 0;
  average_count = 0U;
  average_index = 0U;
}

/* Average the newest five net readings, or all available readings at start. */
static int32_t HX711_AverageAdd(int32_t net)
{
  if (average_count == HX711_AVERAGE_SAMPLES)
  {
    average_sum -= average_samples[average_index];
  }
  else
  {
    ++average_count;
  }

  average_samples[average_index] = net;
  average_sum += net;
  average_index = (uint8_t)((average_index + 1U) % HX711_AVERAGE_SAMPLES);

  return (int32_t)(average_sum / average_count);
}

/* Keep the whole display row 16 characters long so old digits are erased. */
static void OLED_ShowWeightTenths(int32_t tenths)
{
  char display_line[17];
  uint32_t magnitude = (tenths < 0) ? (uint32_t)(-tenths) :
                                       (uint32_t)tenths;
  int length = snprintf(display_line, sizeof(display_line),
                        "G %s%lu.%01lu g", (tenths < 0) ? "-" : "",
                        (unsigned long)(magnitude / 10U),
                        (unsigned long)(magnitude % 10U));

  if (length < 0 || length > 16)
  {
    return;
  }
  while (length < 16)
  {
    display_line[length++] = ' ';
  }
  display_line[16] = '\0';
  OLED_ShowString(2U, 1U, display_line);
}

static void DS18B20_Service(void)
{
  uint32_t now = HAL_GetTick();
  int16_t centi;
  char line[32];
  char display_line[17];
  int length;

  if ((now - temperature_tick) <
      (temperature_converting != 0U ? DS18B20_CONVERSION_MS : DS18B20_RETRY_MS))
  {
    return;
  }

  if (temperature_converting != 0U)
  {
    if (DS18B20_ReadCentiC(&centi) == HAL_OK)
    {
      uint32_t magnitude = (centi < 0) ? (uint32_t)(-(int32_t)centi) :
                                          (uint32_t)centi;
      length = snprintf(line, sizeof(line), "temp_c=%s%lu.%02lu\r\n",
                        (centi < 0) ? "-" : "",
                        (unsigned long)(magnitude / 100U),
                        (unsigned long)(magnitude % 100U));
      if (length > 0 && length < (int)sizeof(line))
      {
        HAL_UART_Transmit(&huart1, (uint8_t *)line, (uint16_t)length, 100U);
      }

      length = snprintf(display_line, sizeof(display_line),
                        "T %s%lu.%02lu C", (centi < 0) ? "-" : "",
                        (unsigned long)(magnitude / 100U),
                        (unsigned long)(magnitude % 100U));
      if (length > 0 && length <= 16)
      {
        while (length < 16)
        {
          display_line[length++] = ' ';
        }
        display_line[16] = '\0';
        OLED_ShowString(3U, 1U, display_line);
      }
    }
    else
    {
      static const uint8_t error_message[] = "temp_error=read_or_crc\r\n";
      HAL_UART_Transmit(&huart1, (uint8_t *)error_message,
                        sizeof(error_message) - 1U, 100U);
      OLED_ShowString(3U, 1U, "TEMP ERROR      ");
    }
  }

  temperature_converting = (DS18B20_StartConversion() == HAL_OK) ? 1U : 0U;
  temperature_tick = HAL_GetTick();
  if (temperature_converting == 0U)
  {
    static const uint8_t missing_message[] = "temp_error=no_presence\r\n";
    HAL_UART_Transmit(&huart1, (uint8_t *)missing_message,
                      sizeof(missing_message) - 1U, 100U);
    OLED_ShowString(3U, 1U, "TEMP ERROR      ");
  }
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */
  GPIO_PinState button_last_sample;
  GPIO_PinState button_stable_state;
  uint32_t button_change_tick;
  uint32_t last_report_tick;
  uint8_t button_armed;

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_USART1_UART_Init();
  /* USER CODE BEGIN 2 */
  HAL_UART_Transmit(&huart1, (uint8_t *)startup_message,
                    sizeof(startup_message) - 1U, 100U);
  OLED_Init();
  OLED_ShowString(1U, 1U, "WEIGHT (g)");
  OLED_ShowString(2U, 1U, "Waiting HX711...");
  OLED_ShowString(3U, 1U, "TEMP WAIT");
  OLED_ShowString(4U, 1U, "PA5 TARE");
  DS18B20_Init();
  temperature_converting = (DS18B20_StartConversion() == HAL_OK) ? 1U : 0U;
  temperature_tick = HAL_GetTick();
  HAL_Delay(500U);

  /* The pan must be empty at startup. Average several conversions for zero. */
  {
    int32_t new_offset;
    char line[64];
    int length;

    if (HX711_Tare(&new_offset) == HAL_OK)
    {
      tare_offset = new_offset;
      tare_valid = 1U;
      HX711_AverageReset();
      length = snprintf(line, sizeof(line), "tare_offset=%ld samples=%u\r\n",
                        (long)tare_offset, (unsigned int)HX711_TARE_SAMPLES);
    }
    else
    {
      length = snprintf(line, sizeof(line),
                        "tare failed; keep pan empty and reset\r\n");
    }

    if (length > 0 && length < (int)sizeof(line))
    {
      HAL_UART_Transmit(&huart1, (uint8_t *)line, (uint16_t)length, 100U);
    }
  }

  button_last_sample = HAL_GPIO_ReadPin(TARE_BUTTON_GPIO_Port, TARE_BUTTON_Pin);
  button_stable_state = button_last_sample;
  button_change_tick = HAL_GetTick();
  button_armed = (button_stable_state == GPIO_PIN_SET) ? 1U : 0U;
  last_report_tick = HAL_GetTick() - RAW_REPORT_INTERVAL_MS;
  last_oled_tick = HAL_GetTick() - OLED_REPORT_INTERVAL_MS;

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    int32_t raw;
    char line[64];
    int length;
    uint32_t now = HAL_GetTick();
    GPIO_PinState button_sample = HAL_GPIO_ReadPin(TARE_BUTTON_GPIO_Port,
                                                    TARE_BUTTON_Pin);

    /* Accept a change only after it remains unchanged for the debounce time. */
    if (button_sample != button_last_sample)
    {
      button_last_sample = button_sample;
      button_change_tick = now;
    }
    if (button_last_sample != button_stable_state &&
        (now - button_change_tick) >= TARE_BUTTON_DEBOUNCE_MS)
    {
      button_stable_state = button_last_sample;
      if (button_stable_state == GPIO_PIN_SET)
      {
        button_armed = 1U;
      }
      else if (button_armed != 0U)
      {
        int32_t new_offset;
        /* A held button cannot start a second tare until it is released. */
        button_armed = 0U;

        if (HX711_Tare(&new_offset) == HAL_OK)
        {
          tare_offset = new_offset;
          tare_valid = 1U;
          HX711_AverageReset();
          length = snprintf(line, sizeof(line), "tare_button_offset=%ld\r\n",
                            (long)tare_offset);
        }
        else
        {
          length = snprintf(line, sizeof(line),
                            "tare button failed; old offset kept\r\n");
        }

        if (length > 0 && length < (int)sizeof(line))
        {
          HAL_UART_Transmit(&huart1, (uint8_t *)line, (uint16_t)length, 100U);
        }
      }
    }

    /* Keep serial reports spaced out while checking the button every 10 ms. */
    if ((HAL_GetTick() - last_report_tick) >= RAW_REPORT_INTERVAL_MS)
    {
      HAL_StatusTypeDef status;
      last_report_tick = HAL_GetTick();
      status = HX711_Read(&raw, 200U);

      if (status == HAL_OK)
      {
        if (tare_valid != 0U)
        {
          int32_t net = raw - tare_offset;
          int32_t tenths = HX711_NetToTenthsOfGram(net);
          int32_t average_net = HX711_AverageAdd(net);
          int32_t average_tenths = HX711_NetToTenthsOfGram(average_net);
          uint32_t magnitude = (tenths < 0) ? (uint32_t)(-tenths) :
                                               (uint32_t)tenths;
          uint32_t average_magnitude = (average_tenths < 0) ?
                                       (uint32_t)(-average_tenths) :
                                       (uint32_t)average_tenths;

          if ((HAL_GetTick() - last_oled_tick) >= OLED_REPORT_INTERVAL_MS)
          {
            OLED_ShowWeightTenths(average_tenths);
            last_oled_tick = HAL_GetTick();
          }

          length = snprintf(line, sizeof(line),
                            "raw=%ld net=%ld g=%s%lu.%01lu g_avg=%s%lu.%01lu\r\n",
                            (long)raw, (long)net,
                            (tenths < 0) ? "-" : "",
                            (unsigned long)(magnitude / 10U),
                            (unsigned long)(magnitude % 10U),
                            (average_tenths < 0) ? "-" : "",
                            (unsigned long)(average_magnitude / 10U),
                            (unsigned long)(average_magnitude % 10U));
        }
        else
        {
          length = snprintf(line, sizeof(line), "raw=%ld tare=invalid\r\n",
                            (long)raw);
        }
      }
      else
      {
        length = snprintf(line, sizeof(line), "HX711 timeout\r\n");
      }

      if (length > 0 && length < (int)sizeof(line))
      {
        HAL_UART_Transmit(&huart1, (uint8_t *)line, (uint16_t)length, 100U);
      }
    }
    DS18B20_Service();
    HAL_Delay(10U);
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_0) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief USART1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART1_UART_Init(void)
{

  /* USER CODE BEGIN USART1_Init 0 */

  /* USER CODE END USART1_Init 0 */

  /* USER CODE BEGIN USART1_Init 1 */

  /* USER CODE END USART1_Init 1 */
  huart1.Instance = USART1;
  huart1.Init.BaudRate = 115200;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART1_Init 2 */

  /* USER CODE END USART1_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(HX711_SCK_GPIO_Port, HX711_SCK_Pin, GPIO_PIN_RESET);

  /*Configure OLED software I2C pins idle high (open drain). */
  HAL_GPIO_WritePin(GPIOB, OLED_SCL_Pin | OLED_SDA_Pin, GPIO_PIN_SET);

  GPIO_InitStruct.Pin = OLED_SCL_Pin | OLED_SDA_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_OD;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pin : HX711_SCK_Pin */
  GPIO_InitStruct.Pin = HX711_SCK_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(HX711_SCK_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : HX711_DOUT_Pin */
  GPIO_InitStruct.Pin = HX711_DOUT_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(HX711_DOUT_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : TARE_BUTTON_Pin (pressed = low) */
  GPIO_InitStruct.Pin = TARE_BUTTON_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(TARE_BUTTON_GPIO_Port, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* Release the open-drain 1-Wire bus before making PA12 an output. */
  HAL_GPIO_WritePin(DS18B20_DQ_GPIO_Port, DS18B20_DQ_Pin, GPIO_PIN_SET);
  GPIO_InitStruct.Pin = DS18B20_DQ_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_OD;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
  HAL_GPIO_Init(DS18B20_DQ_GPIO_Port, &GPIO_InitStruct);

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
