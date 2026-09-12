#include "xterm_keys.h"

#include <stdio.h>
#include <string.h>

static int failures;

static void
check (KeySym keysym, unsigned int modifier, bool app_cursor,
       const char *expected)
{
  char buf[64];
  bool encoded = xterm_key_sequence (keysym, modifier, app_cursor,
                                     buf, sizeof buf);

  if (!encoded || strcmp (buf, expected))
    {
      fprintf (stderr, "keysym 0x%lx modifier %u: got %s, expected %s\n",
               (unsigned long)keysym, modifier,
               encoded ? buf : "<not encoded>", expected);
      ++failures;
    }
}

int
main ()
{
  check (XK_Up, 1, false, "\033[A");
  check (XK_Up, 1, true, "\033OA");
  check (XK_Left, 2, false, "\033[1;2D");
  check (XK_Right, 8, true, "\033[1;8C");
  check (XK_Home, 1, false, "\033[H");
  check (XK_End, 1, true, "\033OF");
  check (XK_Home, 5, true, "\033[1;5H");
  check (XK_Insert, 1, false, "\033[2~");
  check (XK_Delete, 3, false, "\033[3;3~");
  check (XK_Prior, 6, false, "\033[5;6~");
  check (XK_Next, 7, false, "\033[6;7~");

  check (XK_F1, 1, false, "\033OP");
  check (XK_F4, 4, false, "\033[1;4S");
  check (XK_F5, 1, false, "\033[15~");
  check (XK_F12, 8, false, "\033[24;8~");

  // physical F13-F35 use xterm's extended numeric key parameters
  check (XK_F13, 1, false, "\033[25~");
  check (XK_F24, 1, false, "\033[45~");
  check (XK_F25, 1, false, "\033[46~");
  check (XK_F35, 1, false, "\033[56~");
  check (XK_F13, 5, false, "\033[25;5~");

  if (xterm_key_sequence (XK_Return, 1, false, 0, 0))
    {
      fputs ("Return was incorrectly treated as a managed key\n", stderr);
      ++failures;
    }

  return failures != 0;
}
