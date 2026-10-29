#!/usr/bin/env python3
"""Run on a disposable DISPLAY, for example with xvfb-run -a."""

import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import time
import traceback
import tty


MODES = (9, 1000, 1002, 1003, 1004, 1005, 1006, 1015, 2004)
PARAMS = ";".join(map(str, MODES))
PASTE = b"mouse-reset-paste"


def wait_for(predicate, description, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise RuntimeError("timed out: " + description)
        time.sleep(0.01)


def receive(duration=0.1):
    data = bytearray()
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        if select.select([0], [], [], max(0, deadline - time.monotonic()))[0]:
            data.extend(os.read(0, 4096))
    return bytes(data)


def control_modes(modes, operation):
    os.write(1, ("\033[?" + ";".join(map(str, modes)) + operation).encode())


def query_modes():
    receive(0.02)
    for mode in MODES:
        os.write(1, f"\033[?{mode}$p".encode())
    replies = receive()
    states = {int(mode): int(state) for mode, state in re.findall(rb"\x1b\[\?(\d+);(\d+)\$y", replies)}
    if len(states) != len(MODES):
        raise AssertionError("missing mode replies: " + repr(replies))
    return states


def expect_modes(enabled=()):
    actual = query_modes()
    expected = {mode: 1 if mode in enabled else 2 for mode in MODES}
    if actual != expected:
        raise AssertionError(f"mode states {actual}, expected {expected}")


def application(directory, modes):
    tty.setraw(0)
    control_modes(modes, "h")
    (directory / "application.pid").write_text(str(os.getpid()))
    while True:
        signal.pause()


def probe(directory):
    saved = termios.tcgetattr(0)
    tty.setraw(0)
    sequence = 0
    results = []

    def event(action):
        nonlocal sequence
        receive(0.02)
        sequence += 1
        request = directory / f"request-{sequence}.json"
        temporary = request.with_suffix(".tmp")
        temporary.write_text(json.dumps({"action": action}))
        temporary.rename(request)
        # keep reading while the controller delivers actual X events.
        data = bytearray()
        deadline = time.monotonic() + 5
        while not (directory / f"done-{sequence}").exists():
            data.extend(receive(0.02))
            if time.monotonic() > deadline:
                raise RuntimeError("controller did not deliver " + action)
        data.extend(receive())
        return bytes(data)

    def check(name, function):
        control_modes(MODES, "l")
        try:
            function()
            results.append((name, None))
        except Exception:
            results.append((name, traceback.format_exc()))

    def reset_case(tracking, encoding):
        active = (tracking, 1004, 2004) + ((encoding,) if encoding else ())
        control_modes(active, "h")
        expect_modes(active)
        control_modes(MODES, "s")
        assert event("mouse"), "reporting was not active before RIS"
        os.write(1, b"\033c")
        expect_modes()
        assert not event("mouse"), "mouse reports survived RIS"
        control_modes(MODES, "r")
        expect_modes()
        assert not event("mouse"), "saved modes resurrected reporting"
        control_modes(active, "h")
        expect_modes(active)
        assert event("mouse"), "reporting could not be re-enabled"

    def focus_paste_case():
        active = (1003, 1004, 1006, 2004)
        control_modes(active, "h")
        assert event("focus") == b"\033[O\033[I", "missing active focus reports"
        assert event("paste") == b"\033[200~" + PASTE + b"\033[201~", "missing bracketed paste"
        os.write(1, b"\033c")
        expect_modes()
        assert event("focus") == b"", "focus reports survived RIS"
        assert event("paste") == PASTE, "local paste failed or remained bracketed"

    def soft_reset_case():
        control_modes((1003, 1004, 1006, 2004), "h")
        os.write(1, b"\033[!p")
        expect_modes((1003, 1004, 2004))
        assert event("mouse"), "DECSTR unexpectedly disabled motion reporting"

    def interrupted_drag_case():
        control_modes((1003, 1006), "h")
        assert event("hold"), "button press did not reach application"
        os.write(1, b"\033c")
        released = event("release")
        expect_modes()
        assert not released, "interrupted drag reported input after RIS"
        control_modes((1003, 1006), "h")
        assert event("mouse"), "mouse did not recover after interrupted drag"

    def motion_mask_case():
        def selected():
            event("mask")
            return json.loads((directory / f"mask-{sequence}.json").read_text())

        control_modes((1003,), "h")
        assert selected(), "motion event mask was not enabled"
        os.write(1, b"\033c")
        assert not selected(), "motion event mask survived RIS"
        control_modes((1003,), "h")
        assert selected(), "motion event mask could not be re-enabled"

    def killed_case(encoding, death_signal, term):
        pid_file = directory / "application.pid"
        pid_file.unlink(missing_ok=True)
        child = subprocess.Popen([
            sys.executable, __file__, "--application", str(directory),
            f"1003,1004,{encoding},2004",
        ])
        try:
            wait_for(pid_file.exists, "mouse application ready")
            child.send_signal(death_signal)
            assert child.wait(timeout=5) == -death_signal
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
        assert event("mouse"), "killed child did not leave a reproducing mouse mode"
        subprocess.run(["reset"], env={**os.environ, "TERM": term}, check=True, timeout=5)
        tty.setraw(0)
        expect_modes()
        assert not event("mouse"), "reset failed after killed application"
        assert not event("focus"), "focus reports survived reset"
        assert event("paste") == PASTE, "paste remained bracketed after reset"

    try:
        for tracking in (9, 1000, 1002, 1003):
            for encoding in (None, 1005, 1006, 1015):
                check(f"RIS tracking={tracking} encoding={encoding}", lambda: reset_case(tracking, encoding))
        check("focus and clipboard paste around RIS", focus_paste_case)
        check("existing DECSTR behavior", soft_reset_case)
        check("RIS during a held button", interrupted_drag_case)
        if shutil.which("xwininfo"):
            check("X motion event mask around RIS", motion_mask_case)
        for encoding in (1006, 1015):
            for death_signal in (signal.SIGTERM, signal.SIGKILL):
                for term in ("xterm-256color", "rxvt-unicode-256color"):
                    name = f"reset after signal={death_signal} encoding={encoding} TERM={term}"
                    check(name, lambda: killed_case(encoding, death_signal, term))
        (directory / "results.json").write_text(json.dumps(results))
    finally:
        termios.tcsetattr(0, termios.TCSANOW, saved)


def xdo(*args):
    return subprocess.check_output(["xdotool", *map(str, args)], timeout=5, text=True).strip()


def start_terminal(binary, directory, title, command):
    log = (directory / (title + ".log")).open("w")
    process = subprocess.Popen([
        binary, "-title", title, "-geometry", "80x24", "-fn", "fixed",
        "+pb", "-e", *command,
    ], stdout=log, stderr=log, env={**os.environ, "HOME": str(directory)})
    log.close()
    return process


def find_window(title):
    return xdo("search", "--sync", "--name", "^" + title + "$").splitlines()[0]


def stop(process):
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)


def bash_case(binary, directory, use_tmux):
    # the binding captures input without ever executing mouse fragments.
    rc = directory / "bashrc"
    prompts = directory / "prompts"
    line = directory / "line"
    pid_file = directory / "application.pid"
    pid_file.unlink(missing_ok=True)
    prompts.write_text("")
    rc.write_text(
        "PS1='repro$ '\n"
        f"PROMPT_COMMAND='printf . >> {prompts}'\n"
        f"bind -x '\"\\C-x\\C-g\":printf \"%s\" \"$READLINE_LINE\" > {line}'\n"
        + shlex.join([sys.executable, __file__, "--application", str(directory), "1003,1006"]) + "\n"
    )
    shell = ["bash", "--noprofile", "--rcfile", str(rc), "-i"]
    socket = str(directory / "tmux.sock")
    if use_tmux:
        shell = ["tmux", "-S", socket, "-f", "/dev/null", "new-session", *shell]
    title = f"mouse-reset-bash-{os.getpid()}-{int(use_tmux)}"
    process = start_terminal(binary, directory, title, shell)
    try:
        wait_for(pid_file.exists, "Bash child ready")
        window = find_window(title)
        xdo("windowfocus", "--sync", window)
        xdo("windowraise", window)
        os.kill(int(pid_file.read_text()), signal.SIGKILL)
        wait_for(lambda: len(prompts.read_text()) >= 1, "Bash prompt after kill")

        def capture(x):
            line.unlink(missing_ok=True)
            xdo("mousemove", "--sync", "--window", window, x, 120)
            xdo("key", "--clearmodifiers", "ctrl+x", "ctrl+g")
            wait_for(line.exists, "Readline capture")
            return line.read_text()

        assert capture(100), "mouse fragments did not reach Bash before reset"
        count = len(prompts.read_text())
        xdo("key", "--clearmodifiers", "ctrl+c")
        wait_for(lambda: len(prompts.read_text()) > count, "Bash prompt after Ctrl+C")
        count = len(prompts.read_text())
        xdo("type", "--clearmodifiers", "--delay", 1, "reset")
        xdo("key", "Return")
        wait_for(lambda: len(prompts.read_text()) > count, "Bash prompt after reset")
        assert capture(180) == "", "mouse fragments reached Bash after reset"
    finally:
        if use_tmux:
            subprocess.run(["tmux", "-S", socket, "kill-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        stop(process)


def main(binary):
    binary = str(Path(binary).resolve())
    with tempfile.TemporaryDirectory(prefix="urxvt-mouse-reset-") as scratch:
        directory = Path(scratch)
        title = f"mouse-reset-probe-{os.getpid()}"
        sink_title = f"mouse-reset-focus-{os.getpid()}"
        sink = start_terminal(binary, directory, sink_title, ["sleep", "120"])
        process = start_terminal(binary, directory, title, [sys.executable, __file__, "--probe", scratch])
        clipboard = None
        try:
            window, sink_window = find_window(title), find_window(sink_title)
            xdo("windowfocus", "--sync", window)
            index = 1
            deadline = time.monotonic() + 90
            while not (directory / "results.json").exists():
                request = directory / f"request-{index}.json"
                if not request.exists():
                    exited = process.poll() is not None
                    client_ready = Path(binary).name == "rxvtc" and process.returncode == 0
                    if (exited and not client_ready) or time.monotonic() > deadline:
                        raise RuntimeError("probe failed: " + (directory / (title + ".log")).read_text())
                    time.sleep(0.01)
                    continue
                action = json.loads(request.read_text())["action"]
                # focus alone does not raise windows on an X server without a WM.
                xdo("windowraise", window)
                if action == "mouse":
                    xdo("mousemove", "--sync", "--window", window, 100, 100)
                    xdo("mousedown", 1)
                    xdo("mousemove", "--sync", "--window", window, 140, 120)
                    xdo("mouseup", 1)
                    xdo("click", 4)
                elif action == "hold":
                    xdo("mousemove", "--sync", "--window", window, 100, 100)
                    xdo("mousedown", 1)
                elif action == "release":
                    xdo("mousemove", "--sync", "--window", window, 140, 120)
                    xdo("mouseup", 1)
                elif action == "mask":
                    tree = subprocess.check_output(["xwininfo", "-id", window, "-tree"], text=True, timeout=5)
                    children = re.findall(r"(0x[0-9a-f]+).*?(\d+)x(\d+)[+-]\d+[+-]\d+", tree)
                    vt = max(children, key=lambda child: int(child[1]) * int(child[2]))[0]
                    events = subprocess.check_output(["xwininfo", "-id", vt, "-events"], text=True, timeout=5)
                    (directory / f"mask-{index}.json").write_text(json.dumps("PointerMotion" in events))
                elif action == "focus":
                    xdo("windowfocus", "--sync", sink_window)
                    xdo("windowfocus", "--sync", window)
                elif action == "paste":
                    # local selection tests may have replaced CLIPBOARD.
                    if clipboard is not None:
                        stop(clipboard)
                    clipboard = subprocess.Popen(["xclip", "-selection", "clipboard", "-in", "-quiet"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    clipboard.stdin.write(PASTE)
                    clipboard.stdin.close()

                    def clipboard_ready():
                        try:
                            return subprocess.check_output(["xclip", "-selection", "clipboard", "-out"], stderr=subprocess.DEVNULL, timeout=2) == PASTE
                        except subprocess.CalledProcessError:
                            return False

                    wait_for(clipboard_ready, "clipboard owner ready")
                    xdo("click", 2)
                (directory / f"done-{index}").touch()
                index += 1
            results = json.loads((directory / "results.json").read_text())
            process.wait(timeout=5)
        finally:
            stop(process)
            stop(sink)
            if clipboard is not None:
                stop(clipboard)
        for use_tmux in (False, True):
            if use_tmux and not shutil.which("tmux"):
                print("SKIP Bash/tmux: tmux unavailable")
                continue
            try:
                bash_case(binary, directory, use_tmux)
                results.append((f"Bash recovery tmux={use_tmux}", None))
            except Exception:
                results.append((f"Bash recovery tmux={use_tmux}", traceback.format_exc()))
        for name, error in results:
            print(("FAIL " if error else "PASS ") + name)
            if error:
                print(error)
        return int(any(error for _, error in results))


def daemon_suite(binary):
    directory = Path(binary).resolve().parent
    with tempfile.TemporaryDirectory(prefix="urxvt-reset-daemon-") as scratch:
        old_socket = os.environ.get("RXVT_SOCKET")
        socket = str(Path(scratch) / "rxvt.sock")
        os.environ["RXVT_SOCKET"] = socket
        with open(Path(scratch) / "daemon.log", "w") as log:
            daemon = subprocess.Popen([str(directory / "rxvtd"), "-q", "-f", "-o"], stdout=log, stderr=log, env={**os.environ, "HOME": scratch})
        try:
            wait_for(lambda: Path(socket).exists(), "private urxvtd socket")
            print("Testing isolated urxvtd/urxvtc", flush=True)
            return main(str(directory / "rxvtc"))
        finally:
            stop(daemon)
            if old_socket is None:
                os.environ.pop("RXVT_SOCKET", None)
            else:
                os.environ["RXVT_SOCKET"] = old_socket


if __name__ == "__main__":
    if sys.argv[1] == "--application":
        application(Path(sys.argv[2]), tuple(map(int, sys.argv[3].split(","))))
    elif sys.argv[1] == "--probe":
        probe(Path(sys.argv[2]))
    elif sys.argv[1] == "--daemon":
        sys.exit(daemon_suite(sys.argv[2]))
    else:
        sys.exit(main(sys.argv[1]))
