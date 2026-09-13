#ifndef RXVT_OSC52_H_
#define RXVT_OSC52_H_

#include <stddef.h>

namespace rxvt_osc52 {

enum decode_result
{
  decode_ok,
  decode_invalid,
  decode_too_large
};

static inline int
base64_value (unsigned char ch)
{
  if (ch >= 'A' && ch <= 'Z') return ch - 'A';
  if (ch >= 'a' && ch <= 'z') return ch - 'a' + 26;
  if (ch >= '0' && ch <= '9') return ch - '0' + 52;
  if (ch == '+') return 62;
  if (ch == '/') return 63;
  return -1;
}

static inline decode_result
decoded_length (const char *src, size_t len, size_t limit, size_t &out_len)
{
  out_len = 0;

  if (len & 3)
    return decode_invalid;

  size_t padding = len && src[len - 1] == '=' ? 1 : 0;
  if (len > 1 && src[len - 2] == '=')
    padding++;

  out_len = len / 4 * 3 - padding;
  if (out_len > limit)
    return decode_too_large;

  for (size_t pos = 0; pos < len; pos += 4)
    {
      int a = base64_value (src[pos]);
      int b = base64_value (src[pos + 1]);
      bool last = pos + 4 == len;

      if (a < 0 || b < 0)
        return decode_invalid;

      if (src[pos + 2] == '=')
        {
          // only the final quartet may contain canonical two-byte padding.
          if (!last || src[pos + 3] != '=' || (b & 15))
            return decode_invalid;
        }
      else
        {
          int c = base64_value (src[pos + 2]);
          if (c < 0)
            return decode_invalid;

          if (src[pos + 3] == '=')
            {
              if (!last || (c & 3))
                return decode_invalid;
            }
          else if (base64_value (src[pos + 3]) < 0)
            return decode_invalid;
        }
    }

  return decode_ok;
}

static inline decode_result
decode (const char *src, size_t len, size_t limit,
        unsigned char *dst, size_t &out_len)
{
  decode_result result = decoded_length (src, len, limit, out_len);
  if (result != decode_ok)
    return result;

  size_t out = 0;
  for (size_t pos = 0; pos < len; pos += 4)
    {
      int a = base64_value (src[pos]);
      int b = base64_value (src[pos + 1]);
      int c = src[pos + 2] == '=' ? 0 : base64_value (src[pos + 2]);
      int d = src[pos + 3] == '=' ? 0 : base64_value (src[pos + 3]);

      dst[out++] = (a << 2) | (b >> 4);
      if (src[pos + 2] != '=')
        dst[out++] = (b << 4) | (c >> 2);
      if (src[pos + 3] != '=')
        dst[out++] = (c << 6) | d;
    }

  return decode_ok;
}

static inline bool
valid_utf8_text (const unsigned char *src, size_t len)
{
  size_t pos = 0;

  while (pos < len)
    {
      unsigned char a = src[pos];

      // X selections cannot preserve embedded NUL through the existing API.
      if (!a)
        return false;
      if (a < 0x80)
        {
          pos++;
          continue;
        }

      if (a >= 0xc2 && a <= 0xdf && pos + 1 < len
          && (src[pos + 1] & 0xc0) == 0x80)
        pos += 2;
      else if (pos + 2 < len
               && ((a == 0xe0 && src[pos + 1] >= 0xa0 && src[pos + 1] <= 0xbf)
                   || (a >= 0xe1 && a <= 0xec && (src[pos + 1] & 0xc0) == 0x80)
                   || (a == 0xed && src[pos + 1] >= 0x80 && src[pos + 1] <= 0x9f)
                   || (a >= 0xee && a <= 0xef && (src[pos + 1] & 0xc0) == 0x80))
               && (src[pos + 2] & 0xc0) == 0x80)
        pos += 3;
      else if (pos + 3 < len
               && ((a == 0xf0 && src[pos + 1] >= 0x90 && src[pos + 1] <= 0xbf)
                   || (a >= 0xf1 && a <= 0xf3 && (src[pos + 1] & 0xc0) == 0x80)
                   || (a == 0xf4 && src[pos + 1] >= 0x80 && src[pos + 1] <= 0x8f))
               && (src[pos + 2] & 0xc0) == 0x80
               && (src[pos + 3] & 0xc0) == 0x80)
        pos += 4;
      else
        return false;
    }

  return true;
}

} // namespace rxvt_osc52

#endif
