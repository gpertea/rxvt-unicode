#!/usr/bin/env python3

import os
import sys
import time


def main():
    ready, release, terminator = sys.argv[1:4]
    fields = sys.argv[4:]
    ending = b"\x07" if terminator == "bel" else b"\x1b\\"

    if len(fields) % 2:
        raise SystemExit("selector and payload arguments must be paired")

    for index in range(0, len(fields), 2):
        selector = fields[index].encode("ascii")
        payload = fields[index + 1].encode("ascii")
        os.write(sys.stdout.fileno(), b"\x1b]52;" + selector + b";" + payload + ending)

    with open(ready, "w", encoding="ascii"):
        pass

    deadline = time.monotonic() + 10.0
    while not os.path.exists(release) and time.monotonic() < deadline:
        time.sleep(0.05)


if __name__ == "__main__":
    main()
