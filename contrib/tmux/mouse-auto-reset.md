# Foreground-job mouse cleanup in tmux 3.4

The urxvt mouseAutoReset resource observes its own PTY. A surviving tmux client
hides pane job changes from that PTY, so pane cleanup needs the same policy in
the tmux server. This patch applies that policy without shell cleanup hooks.

Source: upstream tmux 3.4 release archive, from
https://github.com/tmux/tmux/releases/download/3.4/tmux-3.4.tar.gz.
Archive SHA256:
`551ab8dea0bf505c0ad6b7bb35ef567cdde0ccb84357df142c254f35a23e19aa`.
The adjacent mouse-auto-reset-3.4.patch changes input.c, input-keys.c,
server-client.c, window.c, tmux.h, options-table.c, and tmux.1.

Apply from a pristine tmux 3.4 source directory, then build normally:

```sh
patch -p1 < /path/to/mouse-auto-reset-3.4.patch
./configure
make
```

The new window/pane option mouse-auto-reset defaults to on. It associates
mouse tracking, encodings, and focus reporting with the observed foreground
job in each pane. Returning to the shell releases those modes. Stopped jobs
regain their modes when resumed. Dead jobs lose their saved state, and retained
dead panes release their mouse modes. RIS clears
cached job state. Bracketed paste and the session-level mouse setting remain
separate policies. Disable this behavior with:

```sh
tmux set-window-option mouse-auto-reset off
```

This requires a patched tmux server; the urxvt patch alone cannot observe a
pane's foreground transitions. The patch does not alter running servers or
apply itself. A surviving SSH connection similarly hides jobs on its remote
PTY; deployment must cover the component that owns that PTY.

Foreground ownership is sampled before parsing/delivering input and with a
100 ms timer while mouse state exists. Very short jobs whose mode-setting
output is parsed after they already returned the PTY cannot always be
attributed. An unavailable foreground-group query preserves existing modes.

Run the urxvt regression suite with a newly built tmux to include pane cases:

```sh
TMUX_MOUSE_CLEANUP_BINARY=/path/to/patched/tmux make check
```

The tests use private X displays, daemon sockets, tmux sockets, and HOME
directories. They exercise termination, suspend/resume, mode encodings,
saved-state reset, focus cleanup, clipboard paste, opt-outs, and tmux mouse
pane selection. The test signal handler only restores raw termios on resume;
it never re-enables mouse modes.
