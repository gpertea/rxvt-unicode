#!/usr/bin/env python3

import os
import select
import sys
import termios
import time
import tty


def main():
    output = sys.argv[1]
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    data = bytearray()

    tty.setraw(fd)
    try:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                data.extend(os.read(fd, 256))
                deadline = time.monotonic() + 0.2
            elif data:
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    with open(output, "wb") as stream:
        stream.write(data)


if __name__ == "__main__":
    main()
