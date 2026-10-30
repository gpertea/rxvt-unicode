#!/usr/bin/env python3
"""Test automatic foreground-job cleanup without shell cleanup hooks."""

import importlib.util
import os
from pathlib import Path
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import tty

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("reset", Path(__file__).with_name("mouse-reset-integration.py"))
reset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset)


def application(directory, label, tracking=1003, encoding=1006):
    ## Bash restores cooked termios on SIGSTOP; the app restores only raw input.
    def resumed(signum, frame):
        tty.setraw(0)
        (directory / (label + ".resumed")).touch()
    signal.signal(signal.SIGCONT, resumed)
    tty.setraw(0)
    modes = [tracking, 1004] + ([encoding] if encoding else [])
    reset.control_modes(modes, "h")
    reset.control_modes(modes, "s")
    (directory / (label + ".pid")).write_text(str(os.getpid()))
    with (directory / (label + ".input")).open("ab", buffering=0) as stream:
        while not (directory / (label + ".exit")).exists():
            if select.select([0], [], [], 0.01)[0]:
                stream.write(os.read(0, 4096))


class Shell:
    def __init__(self, binary, directory, options=(), tmux=None):
        self.directory = directory
        self.prompts = directory / "prompts"
        self.shell_pid = directory / "shell.pid"
        self.line = directory / "line"
        self.x = 80
        self.tracking = 1003
        self.tmux = tmux
        self.client = Path(binary).name == "rxvtc"
        self.socket = str(directory / "pane.sock")
        self.prompts.write_text("")
        rc = directory / "bashrc"
        ## these hooks only record readiness and input; they never reset modes.
        rc.write_text(
            "HISTFILE=/dev/null\n"
            f"printf '%s' \"$$\" > {self.shell_pid}\n"
            "PS1='cleanup$ '\n"
            f"PROMPT_COMMAND='printf . >> {self.prompts}'\n"
            f"bind -x '\"\\C-x\\C-g\":printf \"%s\" \"$READLINE_LINE\" > {self.line}'\n"
        )
        title = f"mouse-cleanup-{os.getpid()}-{directory.name}"
        command = ["bash", "--noprofile", "--rcfile", str(rc), "-i"]
        if tmux:
            command = [tmux, "-S", self.socket, "-f", "/dev/null", "new-session", "-s", "cleanup", *command]
        self.process = reset.start_terminal(binary, directory, title, command, cleanup=True, options=options)
        self.window = reset.find_window(title)
        reset.xdo("windowfocus", "--sync", self.window)
        reset.xdo("windowraise", self.window)
        self.wait_prompt(0)
        if tmux:
            self.tmux_command("set-option", "-g", "mouse", "on")

    def tmux_command(self, *args):
        return subprocess.check_output([self.tmux, "-S", self.socket, *args], text=True, timeout=5).strip()

    def count(self):
        return len(self.prompts.read_text())

    def wait_prompt(self, count):
        reset.wait_for(lambda: self.count() > count, "shell prompt")

    def command(self, command):
        reset.xdo("type", "--clearmodifiers", "--delay", 1, command)
        reset.xdo("key", "Return")

    def start(self, label, tracking=1003, encoding=1006):
        self.tracking = tracking
        self.command(shlex.join([sys.executable, __file__, "--application", str(self.directory), label, str(tracking), str(encoding)]))
        pid = self.directory / (label + ".pid")
        reset.wait_for(pid.exists, "application " + label)
        reset.wait_for((self.directory / (label + ".input")).exists, "input capture " + label)
        self.live_mouse(label)
        return int(pid.read_text())

    def motion(self):
        self.x = 80 + (self.x - 60) % 240
        reset.xdo("windowraise", self.window)
        reset.xdo("mousemove", "--window", self.window, self.x, 120)

    def live_mouse(self, label, resumed=False):
        path = self.directory / (label + ".input")
        before = path.stat().st_size
        self.motion()
        if self.tracking != 1003:
            reset.xdo("click", 1)
        def reported():
            if reset.re.search(rb"\x1b\[(?:M|<|\d+;)", path.read_bytes()[before:]):
                return True
            if resumed:
                ## motion selection is restored by the foreground polling timer.
                self.motion()
            return False
        reset.wait_for(reported, "live mouse report " + label, timeout=2)

    def capture(self, buttons=False):
        self.line.unlink(missing_ok=True)
        self.motion()
        if buttons:
            reset.xdo("click", 1)
        reset.xdo("key", "--clearmodifiers", "ctrl+x", "ctrl+g")
        reset.wait_for(self.line.exists, "Readline capture")
        return self.line.read_text()

    def returned(self, pid, death=signal.SIGKILL):
        count = self.count()
        os.kill(pid, death)
        self.wait_prompt(count)
        assert self.capture() == "", "mouse fragments reached shell without reset"

    def close(self):
        if self.tmux:
            subprocess.run([self.tmux, "-S", self.socket, "kill-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        elif self.shell_pid.exists():
            ## close via the shell's exit path, preserving the daemon's X connection.
            try:
                os.kill(int(self.shell_pid.read_text()), signal.SIGHUP)
            except ProcessLookupError:
                pass
        reset.stop(self.process)


def death_case(shell, death):
    pid = shell.start("application")
    if death == "normal":
        count = shell.count()
        (shell.directory / "application.exit").touch()
        shell.wait_prompt(count)
        assert shell.capture() == "", "normal exit left mouse reports enabled"
    else:
        shell.returned(pid, death)


def resume_case(shell, multiple=False):
    jobs = []
    for label in (("first", "second") if multiple else ("first",)):
        pid = shell.start(label)
        count = shell.count()
        os.kill(pid, signal.SIGSTOP)
        shell.wait_prompt(count)
        assert shell.capture() == "", "stopped application leaked mouse input"
        jobs.append((label, pid))
    for index, (label, pid) in enumerate(jobs):
        shell.command("fg %" + str(index + 1))
        reset.wait_for((shell.directory / (label + ".resumed")).exists, "resumed job")
        shell.live_mouse(label, resumed=True)
        shell.returned(pid)


def disabled_case(shell):
    pid = shell.start("application")
    count = shell.count()
    os.kill(pid, signal.SIGKILL)
    shell.wait_prompt(count)
    assert shell.capture(), "opt-out did not retain legacy mouse behavior"


def reset_suspended_case(shell):
    pid = shell.start("application")
    count = shell.count()
    os.kill(pid, signal.SIGSTOP)
    shell.wait_prompt(count)
    count = shell.count()
    shell.command("printf '\\033c'")
    shell.wait_prompt(count)
    shell.command("fg %1")
    reset.wait_for((shell.directory / "application.resumed").exists, "resumed after RIS")
    time.sleep(0.15)
    path = shell.directory / "application.input"
    before = path.stat().st_size
    shell.motion()
    time.sleep(0.15)
    assert b"\033[<" not in path.read_bytes()[before:], "RIS retained a suspended job's mouse state"
    shell.returned(pid)


def paste_case(shell):
    death_case(shell, signal.SIGKILL)
    payload = b"cleanup-first\ncleanup-second"
    owner = subprocess.Popen(["xclip", "-selection", "clipboard", "-in", "-quiet"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        owner.stdin.write(payload)
        owner.stdin.close()
        def ready():
            try:
                return subprocess.check_output(["xclip", "-selection", "clipboard", "-out"], stderr=subprocess.DEVNULL, timeout=2) == payload
            except subprocess.CalledProcessError:
                return False
        reset.wait_for(ready, "clipboard owner")
        reset.xdo("click", 2)
        ## honor the default Perl dialog for multiline paste instead of disabling it.
        executable = Path(shell.process.args[0]).with_name("rxvt")
        features = subprocess.run([str(executable), "-help"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5).stdout
        if b"options: perl," in features:
            time.sleep(0.15)
            reset.xdo("key", "p")
        assert shell.capture() == payload.decode(), "cleanup broke local or bracketed paste"
    finally:
        reset.stop(owner)


def mode_matrix_case(shell):
    tracking_modes = (1000, 1002, 1003) if shell.tmux else (9, 1000, 1002, 1003)
    encodings = (0, 1005, 1006) if shell.tmux else (0, 1005, 1006, 1015)
    for tracking in tracking_modes:
        for encoding in encodings:
            pid = shell.start(f"mode-{tracking}-{encoding}", tracking, encoding)
            count = shell.count()
            os.kill(pid, signal.SIGKILL)
            shell.wait_prompt(count)
            if shell.tmux:
                time.sleep(0.35) ## avoid turning test clicks into tmux double-clicks.
            assert shell.capture(buttons=True) == "", f"stale mouse modes {tracking}/{encoding}"


def focus_case(shell):
    death_case(shell, signal.SIGKILL)
    title = f"cleanup-focus-sink-{os.getpid()}"
    pid_file = shell.directory / "focus-sink.pid"
    sink = reset.start_terminal(str(Path(shell.process.args[0]).resolve()), shell.directory, title,
        ["sh", "-c", 'printf %s "$$" > "$1"; exec sleep 10', "sh", str(pid_file)], cleanup=True)
    window = reset.find_window(title)
    reset.wait_for(pid_file.exists, "focus sink child")
    try:
        reset.xdo("windowfocus", "--sync", window)
        reset.xdo("windowfocus", "--sync", shell.window)
        assert shell.capture() == "", "focus reports reached shell after cleanup"
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGHUP)
            except ProcessLookupError:
                pass
        reset.stop(sink)


def tmux_client_case(shell):
    socket = str(shell.directory / "tmux.sock")
    label = "pane"
    command = shlex.join([sys.executable, __file__, "--application", str(shell.directory), label])
    try:
        shell.command(shlex.join(["tmux", "-S", socket, "-f", "/dev/null", "new-session", command]))
        path = shell.directory / (label + ".pid")
        reset.wait_for(path.exists, "tmux pane application")
        shell.live_mouse(label)
        client = int(subprocess.check_output(["tmux", "-S", socket, "list-clients", "-F", "#{client_pid}"], text=True).strip())
        shell.returned(client)
    finally:
        subprocess.run(["tmux", "-S", socket, "kill-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)


def tmux_mouse_case(shell):
    original = shell.tmux_command("display-message", "-p", "#{pane_id}")
    second = shell.tmux_command("split-window", "-h", "-d", "-P", "-F", "#{pane_id}", "sleep 60")
    reset.xdo("mousemove", "--sync", "--window", shell.window, 450, 120)
    reset.xdo("click", 1)
    reset.wait_for(lambda: shell.tmux_command("display-message", "-p", "#{pane_id}") == second, "tmux mouse selects second pane")
    reset.xdo("mousemove", "--sync", "--window", shell.window, 100, 120)
    reset.xdo("click", 1)
    reset.wait_for(lambda: shell.tmux_command("display-message", "-p", "#{pane_id}") == original, "tmux mouse selects original pane")
    assert shell.capture() == "", "tmux mouse selection leaked into shell"


def held_terminal_case(shell):
    title = f"cleanup-held-{os.getpid()}"
    process = reset.start_terminal(shell.process.args[0], shell.directory, title,
        [sys.executable, __file__, "--application", str(shell.directory), "held"], cleanup=True, options=("-hold",))
    window = reset.find_window(title)
    pid_file = shell.directory / "held.pid"
    def selected():
        tree = subprocess.check_output(["xwininfo", "-id", window, "-tree"], text=True, timeout=5)
        children = reset.re.findall(r"(0x[0-9a-f]+).*?(\d+)x(\d+)[+-]\d+[+-]\d+", tree)
        vt = max(children, key=lambda child: int(child[1]) * int(child[2]))[0]
        return "PointerMotion" in subprocess.check_output(["xwininfo", "-id", vt, "-events"], text=True, timeout=5)
    try:
        reset.wait_for(pid_file.exists, "held application")
        reset.wait_for(selected, "held application mouse mode")
        os.kill(int(pid_file.read_text()), signal.SIGKILL)
        reset.wait_for(lambda: not selected(), "held terminal mouse cleanup")
    finally:
        if shell.client:
            subprocess.run(["xdotool", "windowclose", window], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        reset.stop(process)


def dead_pane_case(shell):
    shell.tmux_command("set-window-option", "remain-on-exit", "on")
    command = shlex.join([sys.executable, __file__, "--application", str(shell.directory), "dead"])
    shell.tmux_command("respawn-pane", "-k", command)
    path = shell.directory / "dead.pid"
    reset.wait_for(path.exists, "dead-pane application")
    reset.wait_for((shell.directory / "dead.input").exists, "dead-pane input capture")
    shell.live_mouse("dead")
    os.kill(int(path.read_text()), signal.SIGKILL)
    reset.wait_for(lambda: shell.tmux_command("display-message", "-p", "#{pane_dead}") == "1", "pane remains after exit")
    reset.wait_for(lambda: shell.tmux_command("display-message", "-p", "#{mouse_any_flag}") == "0", "dead pane mouse cleanup")


def main(binary, baseline=False, selected=None, panes=False):
    binary = str(Path(binary).resolve())
    cases = [("SIGKILL without reset", lambda shell: death_case(shell, signal.SIGKILL), ())]
    if not baseline:
        cases += [
            ("normal exit without reset", lambda shell: death_case(shell, "normal"), ()),
            ("SIGTERM without reset", lambda shell: death_case(shell, signal.SIGTERM), ()),
            ("suspend and resume", resume_case, ()),
            ("two suspended jobs", lambda shell: resume_case(shell, True), ()),
            ("RIS discards suspended state", reset_suspended_case, ()),
            ("clipboard and bracketed paste after cleanup", paste_case, ()),
            ("tracking and encoding matrix", mode_matrix_case, ()),
            ("focus reporting cleanup", focus_case, ()),
        ]
        if panes:
            def pane_disabled(shell):
                shell.tmux_command("set-window-option", "mouse-auto-reset", "off")
                disabled_case(shell)
            cases += [("tmux pane opt-out", pane_disabled, ()), ("tmux mouse pane selection", tmux_mouse_case, ())]
            cases.append(("dead pane releases mouse mode", dead_pane_case, ()))
        else:
            cases += [
                ("CLI opt-out", disabled_case, ("+mouse-auto-reset",)),
                ("resource opt-out", disabled_case, ("-xrm", "URxvt.mouseAutoReset: false")),
                ("CLI enable overrides resource", lambda shell: death_case(shell, signal.SIGKILL), ("-xrm", "URxvt.mouseAutoReset: false", "-mouse-auto-reset")),
            ]
            if reset.shutil.which("xwininfo"):
                cases.append(("held terminal releases mouse mode", held_terminal_case, ()))
        if not panes and reset.shutil.which("tmux"):
            cases.append(("tmux client SIGKILL", tmux_client_case, ()))
    failed = 0
    if selected is not None:
        cases = [case for case in cases if case[0] == selected]
        assert cases, "unknown test case: " + selected
    for index, (name, test, options) in enumerate(cases):
        with tempfile.TemporaryDirectory(prefix=f"urxvt-cleanup-{index}-") as scratch:
            shell = None
            try:
                tmux = os.environ.get("TMUX_MOUSE_CLEANUP_BINARY", "tmux") if panes else None
                shell = Shell(binary, Path(scratch), options, tmux)
                test(shell)
                for log in Path(scratch).glob("*.log"):
                    assert "unable to initialize perl-interpreter" not in log.read_text(), "Perl initialization failed: " + log.read_text()
                print("PASS " + name, flush=True)
            except Exception:
                print("FAIL " + name + "\n" + traceback.format_exc(), flush=True)
                for log in Path(scratch).glob("*.log"):
                    print(log.read_text(), flush=True)
                failed += 1
            finally:
                if shell is not None:
                    shell.close()
    return int(failed != 0)


def run_all(binary):
    result = main(binary)
    if os.environ.get("TMUX_MOUSE_CLEANUP_BINARY"):
        print("Testing patched tmux panes", flush=True)
        result |= main(binary, panes=True)
    return result


if __name__ == "__main__":
    if sys.argv[1] == "--application":
        application(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 1003, int(sys.argv[5]) if len(sys.argv) > 5 else 1006)
    elif sys.argv[1] == "--daemon":
        run = (lambda binary: main(binary, panes=True)) if "--panes" in sys.argv[3:] else run_all
        sys.exit(reset.daemon_suite(sys.argv[2], run))
    else:
        selected = sys.argv[sys.argv.index("--case") + 1] if "--case" in sys.argv else None
        if selected or "--baseline" in sys.argv or "--panes" in sys.argv:
            sys.exit(main(sys.argv[1], "--baseline" in sys.argv[2:], selected, "--panes" in sys.argv[2:]))
        sys.exit(run_all(sys.argv[1]))
