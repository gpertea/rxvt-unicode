#ifndef XTERM_KEYS_H_
#define XTERM_KEYS_H_

#include <X11/Xlib.h>
#include <X11/keysym.h>
#include <stddef.h>
#include <stdio.h>

static inline bool
xterm_key_is_managed (KeySym keysym)
{
  return (keysym >= XK_Left && keysym <= XK_Down)
         || keysym == XK_Home || keysym == XK_End
         || keysym == XK_Insert || keysym == XK_Delete
         || keysym == XK_Prior || keysym == XK_Next
         || (keysym >= XK_F1 && keysym <= XK_F35)
         || (keysym >= XK_KP_Home && keysym <= XK_KP_Begin)
         || keysym == XK_KP_Insert || keysym == XK_KP_Delete;
}

/* encode the keys covered by the xterm compatibility profile */
static inline bool
xterm_key_sequence (KeySym keysym, unsigned int modifier, bool app_cursor,
                    char *buf, size_t buflen)
{
  static const int function_params[] = { 15, 17, 18, 19, 20, 21, 23, 24 };
  static const int extended_function_params[] = {
    25, 26, 28, 29, 31, 32, 33, 34, 42, 43, 44, 45,
    46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56
  };

  switch (keysym)
    {
      case XK_Up:
      case XK_Down:
      case XK_Right:
      case XK_Left:
        {
          char final = "DACB"[keysym - XK_Left];
          if (modifier == 1)
            snprintf (buf, buflen, "\033%c%c", app_cursor ? 'O' : '[', final);
          else
            snprintf (buf, buflen, "\033[1;%u%c", modifier, final);
          return true;
        }

      case XK_Home:
      case XK_End:
        {
          char final = keysym == XK_Home ? 'H' : 'F';
          if (modifier == 1)
            snprintf (buf, buflen, "\033%c%c", app_cursor ? 'O' : '[', final);
          else
            snprintf (buf, buflen, "\033[1;%u%c", modifier, final);
          return true;
        }

      case XK_Insert:
      case XK_Delete:
      case XK_Prior:
      case XK_Next:
        {
          int param = keysym == XK_Insert ? 2 : keysym == XK_Delete ? 3
                    : keysym == XK_Prior ? 5 : 6;
          if (modifier == 1)
            snprintf (buf, buflen, "\033[%d~", param);
          else
            snprintf (buf, buflen, "\033[%d;%u~", param, modifier);
          return true;
        }

      default:
        break;
    }

  if (keysym < XK_F1 || keysym > XK_F35)
    return false;

  int function = keysym - XK_F1;
  if (function >= 12)
    {
      int param = extended_function_params[function - 12];
      if (modifier == 1)
        snprintf (buf, buflen, "\033[%d~", param);
      else
        snprintf (buf, buflen, "\033[%d;%u~", param, modifier);
      return true;
    }

  if (function < 4)
    {
      char final = 'P' + function;
      if (modifier == 1)
        snprintf (buf, buflen, "\033O%c", final);
      else
        snprintf (buf, buflen, "\033[1;%u%c", modifier, final);
    }
  else
    {
      int param = function_params[function - 4];
      if (modifier == 1)
        snprintf (buf, buflen, "\033[%d~", param);
      else
        snprintf (buf, buflen, "\033[%d;%u~", param, modifier);
    }

  return true;
}

#endif
