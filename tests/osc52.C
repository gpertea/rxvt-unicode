#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "osc52.h"

static void
fail (const char *name)
{
  fprintf (stderr, "OSC 52 test failed: %s\n", name);
  exit (1);
}

static void
expect_decode (const char *name, const char *encoded, const char *expected)
{
  unsigned char output[128];
  size_t output_len = 0;
  rxvt_osc52::decode_result result = rxvt_osc52::decode (
    encoded, strlen (encoded), sizeof output, output, output_len);

  if (result != rxvt_osc52::decode_ok
      || output_len != strlen (expected)
      || memcmp (output, expected, output_len))
    fail (name);
}

static void
expect_invalid (const char *name, const char *encoded)
{
  unsigned char output[128];
  size_t output_len = 0;

  if (rxvt_osc52::decode (encoded, strlen (encoded), sizeof output,
                          output, output_len) != rxvt_osc52::decode_invalid)
    fail (name);
}

int
main ()
{
  expect_decode ("empty", "", "");
  expect_decode ("one padding", "Zm8=", "fo");
  expect_decode ("two padding", "Zg==", "f");
  expect_decode ("no padding", "Zm9v", "foo");
  expect_decode ("utf8", "Y2Fmw6k=", "caf\xc3\xa9");

  expect_invalid ("short", "Zg=");
  expect_invalid ("invalid alphabet", "Zm$=");
  expect_invalid ("interior padding", "Zg==Zm8=");
  expect_invalid ("noncanonical one padding", "Zm9=");
  expect_invalid ("noncanonical two padding", "Zh==");

  unsigned char output[8];
  size_t output_len = 0;
  if (rxvt_osc52::decode ("Zm9v", 4, 2, output, output_len)
      != rxvt_osc52::decode_too_large)
    fail ("size limit");

  const unsigned char ascii[] = "clipboard\n";
  const unsigned char utf8[] = "caf\xc3\xa9";
  const unsigned char overlong[] = { 0xc0, 0x80 };
  const unsigned char surrogate[] = { 0xed, 0xa0, 0x80 };
  const unsigned char nul[] = { 'a', 0, 'b' };

  if (!rxvt_osc52::valid_utf8_text (ascii, sizeof ascii - 1)
      || !rxvt_osc52::valid_utf8_text (utf8, sizeof utf8 - 1)
      || rxvt_osc52::valid_utf8_text (overlong, sizeof overlong)
      || rxvt_osc52::valid_utf8_text (surrogate, sizeof surrogate)
      || rxvt_osc52::valid_utf8_text (nul, sizeof nul))
    fail ("UTF-8 validation");

  return 0;
}
