#!/usr/bin/env python3

import os
import select
import sys
import termios
import time
import tty


def main():
    output = sys.argv[1]
    bracketed = len(sys.argv) > 2 and sys.argv[2] == "bracketed"
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    data = bytearray()

    tty.setraw(fd)
    try:
        modes = b"\x1b[?1000h\x1b[?1006h"
        if bracketed:
            modes += b"\x1b[?2004h"
        os.write(sys.stdout.fileno(), modes)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                data.extend(os.read(fd, 4096))
                deadline = time.monotonic() + 0.2
            elif data:
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    with open(output, "wb") as stream:
        stream.write(data)


if __name__ == "__main__":
    main()
