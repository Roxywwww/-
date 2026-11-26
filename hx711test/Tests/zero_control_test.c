#include <stdint.h>
#include "zero_control.h"

#define CHECK(condition, number) do { if (!(condition)) return (number); } while (0)

static uint8_t pixels[8][128];
static uint8_t cursor_page, cursor_x;
static uint32_t pixel_writes;
static void OLED_SetCursor(uint8_t page, uint8_t x)
{
  cursor_page = page;
  cursor_x = x;
}
static void OLED_WriteData(uint8_t data)
{
  if (cursor_page < 8U && cursor_x < 128U)
    pixels[cursor_page][cursor_x++] = data;
  ++pixel_writes;
}
/* The runner extracts this function verbatim from the production oled.c. */
#include "oled_progress_under_test.inc"

int main(void)
{
  ZeroKey key;
  ZeroSamples samples;
  int32_t offset = 12345;
  uint32_t t, start;
  int i, result;

  /* Bounce does not press the key; a short action happens only on release. */
  ZeroKey_Init(&key, 0U, 0U);
  CHECK(ZeroKey_Update(&key, 1U, 10U) == ZERO_KEY_NONE, 1);
  CHECK(ZeroKey_Update(&key, 0U, 20U) == ZERO_KEY_NONE, 2);
  CHECK(ZeroKey_Update(&key, 1U, 100U) == ZERO_KEY_NONE, 3);
  CHECK(ZeroKey_Update(&key, 1U, 130U) == ZERO_KEY_NONE, 4);
  CHECK(ZeroKey_Update(&key, 0U, 250U) == ZERO_KEY_NONE, 5);
  CHECK(ZeroKey_Update(&key, 0U, 280U) == ZERO_KEY_SHORT, 6);
  CHECK(ZeroKey_Update(&key, 0U, 500U) == ZERO_KEY_NONE, 7);

  /* Releasing part-way through the hold cancels without also doing a tare. */
  ZeroKey_Init(&key, 0U, 0U);
  ZeroKey_Update(&key, 1U, 100U);
  ZeroKey_Update(&key, 1U, 130U);
  ZeroKey_Update(&key, 0U, 1130U);
  CHECK(ZeroKey_Update(&key, 0U, 1160U) == ZERO_KEY_CANCEL, 8);

  /* A long hold fires once, does not repeat, and has no short release action. */
  ZeroKey_Init(&key, 0U, 0U);
  ZeroKey_Update(&key, 1U, 100U);
  ZeroKey_Update(&key, 1U, 130U);
  CHECK(ZeroKey_Update(&key, 1U, 3129U) == ZERO_KEY_NONE, 9);
  CHECK(ZeroKey_Update(&key, 1U, 3130U) == ZERO_KEY_LONG, 10);
  for (t = 3140U; t < 11000U; t += 10U)
    CHECK(ZeroKey_Update(&key, 1U, t) == ZERO_KEY_NONE, 11);
  ZeroKey_Update(&key, 0U, 11000U);
  CHECK(ZeroKey_Update(&key, 0U, 11030U) == ZERO_KEY_NONE, 12);

  /* A release just before the deadline cannot finish during release debounce. */
  ZeroKey_Init(&key, 0U, 0U);
  ZeroKey_Update(&key, 1U, 100U);
  ZeroKey_Update(&key, 1U, 130U);
  CHECK(ZeroKey_Update(&key, 0U, 3129U) == ZERO_KEY_NONE, 13);
  CHECK(ZeroKey_Update(&key, 0U, 3130U) == ZERO_KEY_NONE, 14);
  CHECK(ZeroKey_Update(&key, 0U, 3159U) == ZERO_KEY_CANCEL, 15);

  /* Held at boot: no action until released and deliberately pressed again. */
  ZeroKey_Init(&key, 1U, 0U);
  CHECK(ZeroKey_Update(&key, 1U, 9000U) == ZERO_KEY_NONE, 16);
  ZeroKey_Update(&key, 0U, 9100U);
  CHECK(ZeroKey_Update(&key, 0U, 9130U) == ZERO_KEY_NONE, 17);
  ZeroKey_Update(&key, 1U, 9200U);
  ZeroKey_Update(&key, 1U, 9230U);
  CHECK(ZeroKey_Update(&key, 1U, 12230U) == ZERO_KEY_LONG, 18);

  /* Millisecond-counter wrap-around preserves the hold duration. */
  start = 0xFFFFFF00U;
  ZeroKey_Init(&key, 0U, start);
  ZeroKey_Update(&key, 1U, start + 10U);
  ZeroKey_Update(&key, 1U, start + 40U);
  CHECK(ZeroKey_Update(&key, 1U, start + 3040U) == ZERO_KEY_LONG, 19);

  /* Only 16 fresh readings may commit an offset. */
  ZeroSamples_Init(&samples);
  for (i = 0; i < 16; ++i)
  {
    result = ZeroSamples_Add(&samples, 32000 + i, 178, &offset);
    CHECK(result == (i == 15 ? 1 : 0), 20);
    if (i < 15) CHECK(offset == 12345, 21);
  }
  CHECK(offset == 32007, 22);
  CHECK(ZeroSamples_Add(&samples, 32000, 178, &offset) == -1, 23);

  /* Rejected motion and ADC saturation preserve the previous offset. */
  ZeroSamples_Init(&samples);
  CHECK(ZeroSamples_Add(&samples, 32000, 178, &offset) == 0, 24);
  CHECK(ZeroSamples_Add(&samples, 32179, 178, &offset) == -1, 25);
  CHECK(offset == 32007, 26);
  ZeroSamples_Init(&samples);
  CHECK(ZeroSamples_Add(&samples, 8388607, 178, &offset) == -1, 27);
  CHECK(ZeroSamples_Add(&samples, -8388608, 178, &offset) == -1, 28);
  CHECK(offset == 32007, 29);

  /* Ordinary tare allows signed readings; the accumulator handles ADC limits. */
  ZeroSamples_Init(&samples);
  for (i = 0; i < 16; ++i)
    result = ZeroSamples_Add(&samples, -32000 - i, 0, &offset);
  CHECK(result == 1 && offset == -32007, 30);
  ZeroSamples_Init(&samples);
  for (i = 0; i < 16; ++i)
    result = ZeroSamples_Add(&samples, 8388606, 0, &offset);
  CHECK(result == 1 && offset == 8388606, 31);

  /* Exercise the actual OLED bar drawing at empty, half, full and bad input. */
  OLED_ShowProgressBar(4U, 0U);
  CHECK(pixel_writes == 256U && cursor_page == 7U, 32);
  CHECK(pixels[6][0] == 0xFFU && pixels[7][127] == 0xFFU, 33);
  CHECK(pixels[6][3] == 0x01U && pixels[7][3] == 0x80U, 34);
  OLED_ShowProgressBar(4U, 50U);
  CHECK(pixels[6][63] == 0xFDU && pixels[6][64] == 0x01U, 35);
  OLED_ShowProgressBar(4U, 100U);
  CHECK(pixels[6][124] == 0xFDU && pixels[7][124] == 0xBFU, 36);
  CHECK(pixels[6][125] == 0x01U, 37);
  OLED_ShowProgressBar(4U, 255U);
  CHECK(pixels[6][124] == 0xFDU, 38);
  t = pixel_writes;
  OLED_ShowProgressBar(0U, 50U);
  OLED_ShowProgressBar(5U, 50U);
  CHECK(pixel_writes == t, 39);
  return 0;
}
