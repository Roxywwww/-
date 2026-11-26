#ifndef ZERO_CONTROL_H
#define ZERO_CONTROL_H

#include <stdint.h>

#define ZERO_KEY_DEBOUNCE_MS 30U
#define ZERO_KEY_SHORT_MS 500U
#define ZERO_KEY_HOLD_MS 3000U
#define ZERO_SAMPLE_COUNT 16U

typedef enum {
  ZERO_KEY_NONE = 0,
  ZERO_KEY_SHORT,
  ZERO_KEY_LONG,
  ZERO_KEY_CANCEL
} ZeroKeyEvent;

typedef struct {
  uint32_t changed_at;
  uint32_t pressed_at;
  uint8_t last_pressed;
  uint8_t stable_pressed;
  uint8_t armed;
  uint8_t active;
  uint8_t long_fired;
} ZeroKey;

typedef struct {
  int64_t sum;
  int32_t minimum;
  int32_t maximum;
  uint8_t count;
} ZeroSamples;

/* A key held at boot must first be released before it can perform an action. */
static void ZeroKey_Init(ZeroKey *key, uint8_t pressed, uint32_t now)
{
  key->changed_at = now;
  key->pressed_at = now;
  key->last_pressed = pressed;
  key->stable_pressed = pressed;
  key->armed = (pressed == 0U) ? 1U : 0U;
  key->active = 0U;
  key->long_fired = 0U;
}

static ZeroKeyEvent ZeroKey_Update(ZeroKey *key, uint8_t pressed, uint32_t now)
{
  if (pressed != key->last_pressed)
  {
    key->last_pressed = pressed;
    key->changed_at = now;
  }
  if (pressed != key->stable_pressed &&
      (uint32_t)(now - key->changed_at) >= ZERO_KEY_DEBOUNCE_MS)
  {
    key->stable_pressed = pressed;
    if (pressed != 0U)
    {
      if (key->armed != 0U)
      {
        key->armed = 0U;
        key->active = 1U;
        key->long_fired = 0U;
        key->pressed_at = now;
      }
    }
    else
    {
      key->armed = 1U;
      if (key->active != 0U)
      {
        uint32_t duration = key->changed_at - key->pressed_at;
        key->active = 0U;
        if (key->long_fired == 0U)
        {
          return (duration < ZERO_KEY_SHORT_MS) ? ZERO_KEY_SHORT : ZERO_KEY_CANCEL;
        }
      }
    }
  }
  /* Do not complete a hold after the physical key has already been released. */
  if (key->active != 0U && key->long_fired == 0U && pressed != 0U &&
      (uint32_t)(now - key->pressed_at) >= ZERO_KEY_HOLD_MS)
  {
    key->long_fired = 1U;
    return ZERO_KEY_LONG;
  }
  return ZERO_KEY_NONE;
}

static void ZeroSamples_Init(ZeroSamples *samples)
{
  samples->sum = 0;
  samples->minimum = 0;
  samples->maximum = 0;
  samples->count = 0U;
}

/* Return -1 for saturation/motion, 0 while collecting, and 1 when complete.
   A non-positive maximum span disables the motion check (ordinary tare). */
static int ZeroSamples_Add(ZeroSamples *samples, int32_t raw,
                           int32_t maximum_span, int32_t *offset)
{
  if (raw <= -8388608L || raw >= 8388607L || samples->count >= ZERO_SAMPLE_COUNT)
  {
    return -1;
  }
  if (samples->count == 0U)
  {
    samples->minimum = raw;
    samples->maximum = raw;
  }
  if (raw < samples->minimum) samples->minimum = raw;
  if (raw > samples->maximum) samples->maximum = raw;
  if (maximum_span > 0 && samples->maximum - samples->minimum > maximum_span)
  {
    return -1;
  }
  samples->sum += raw;
  ++samples->count;
  if (samples->count == ZERO_SAMPLE_COUNT)
  {
    *offset = (int32_t)(samples->sum / ZERO_SAMPLE_COUNT);
    return 1;
  }
  return 0;
}

#endif
