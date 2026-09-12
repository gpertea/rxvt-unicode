#!/usr/bin/env python3

import os
import select
import sys
import termios
import time
import tty


def main():
    output, selector, terminator = sys.argv[1:4]
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    ending = b"\x07" if terminator == "bel" else b"\x1b\\"

    tty.setraw(fd)
    try:
        os.write(sys.stdout.fileno(), b"\x1b]" + selector.encode() + b";?" + ending)
        data = bytearray()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                data.extend(os.read(fd, 256))
                if data.endswith(ending):
                    break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    with open(output, "wb") as stream:
        stream.write(data)


if __name__ == "__main__":
    main()
