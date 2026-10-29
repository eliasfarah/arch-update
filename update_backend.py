"""Run yay interactively while keeping authentication inside the application."""

import codecs
import errno
import fcntl
import json
import os
import pty
import select
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import threading
from pathlib import Path


class AuthenticationRequest:
    def __init__(self):
        self.event = threading.Event()
        self.password = None
        self._lock = threading.Lock()

    def respond(self, password):
        with self._lock:
            if not self.event.is_set():
                self.password = password
                self.event.set()


class UpdateSession:
    """A single child process with a private askpass channel and a PTY."""

    def __init__(self, command, on_output, on_authentication, on_exit):
        self.command = list(command)
        self.on_output = on_output
        self.on_authentication = on_authentication
        self.on_exit = on_exit
        self._stop = threading.Event()
        self._master = None
        self._process = None
        self._server = None
        self._tempdir = None
        self._auth_thread = None

    def start(self):
        base = Path(__file__).resolve().parent
        askpass = base / "askpass.py"
        runner = base / "pty_runner.py"
        if not askpass.is_file() or not os.access(askpass, os.X_OK) or not runner.is_file():
            raise RuntimeError("Os componentes da Central estão incompletos. Reinstale o aplicativo.")

        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if not runtime_dir or not os.path.isdir(runtime_dir) or len(os.fsencode(runtime_dir)) > 65:
            runtime_dir = None
        master = None
        slave = None
        try:
            self._tempdir = tempfile.TemporaryDirectory(prefix="arch-update-", dir=runtime_dir)
            socket_path = os.path.join(self._tempdir.name, "askpass.sock")
            self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._server.bind(socket_path)
            os.chmod(socket_path, 0o600)
            self._server.listen(4)
            self._server.settimeout(0.5)
            master, slave = pty.openpty()
            self._master = master
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
            attrs = termios.tcgetattr(slave)
            attrs[3] &= ~(termios.ECHO | termios.ECHONL)
            termios.tcsetattr(slave, termios.TCSANOW, attrs)
            env = os.environ.copy()
            env.update({
                "SUDO_ASKPASS": str(askpass),
                "ARCH_UPDATE_ASKPASS_SOCKET": socket_path,
                "PAGER": "cat",
                "TERM": "dumb",
                "NO_COLOR": "1",
                "LC_ALL": "C",
            })
            self._process = subprocess.Popen(
                [sys.executable, str(runner), *self.command],
                stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True,
            )
        except Exception:
            if master is not None:
                os.close(master)
            self._master = None
            if self._server:
                self._server.close()
            if self._tempdir:
                self._tempdir.cleanup()
            raise
        finally:
            if slave is not None:
                os.close(slave)

        self._auth_thread = threading.Thread(target=self._serve_authentication, daemon=True)
        self._auth_thread.start()
        threading.Thread(target=self._read_output, daemon=True).start()

    def send_response(self, response, secret=False):
        if self._master is None or self._process is None or self._process.poll() is not None:
            return False
        try:
            if secret:
                attrs = termios.tcgetattr(self._master)
                attrs[3] &= ~(termios.ECHO | termios.ECHONL)
                termios.tcsetattr(self._master, termios.TCSANOW, attrs)
            os.write(self._master, (response + "\n").encode("utf-8"))
            return True
        except OSError:
            return False

    def _serve_authentication(self):
        while not self._stop.is_set():
            try:
                connection, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                try:
                    connection.settimeout(5)
                    if hasattr(socket, "SO_PEERCRED"):
                        _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        if uid != os.getuid():
                            continue
                    greeting = bytearray()
                    while b"\n" not in greeting and len(greeting) < 64:
                        chunk = connection.recv(64 - len(greeting))
                        if not chunk:
                            break
                        greeting.extend(chunk)
                    if bytes(greeting) != b"arch-update-askpass\n":
                        continue
                    request = AuthenticationRequest()
                    try:
                        self.on_authentication(request)
                    except Exception:
                        request.respond(None)
                    while not request.event.wait(0.2):
                        if self._stop.is_set():
                            request.respond(None)
                    payload = json.dumps({"password": request.password}, ensure_ascii=False).encode("utf-8") + b"\n"
                    connection.sendall(payload)
                    request.password = None
                except (OSError, ValueError):
                    continue

    def _read_output(self):
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            while True:
                ready, _, _ = select.select([self._master], [], [], 0.2)
                if ready:
                    try:
                        data = os.read(self._master, 8192)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            break
                        raise
                    if not data:
                        break
                    text = decoder.decode(data)
                    if text:
                        self.on_output(text)
                elif self._process.poll() is not None:
                    break
            tail = decoder.decode(b"", final=True)
            if tail:
                self.on_output(tail)
            code = self._process.wait()
        except Exception as exc:
            self.on_output(f"\nErro ao acompanhar a atualização: {exc}\n")
            code = self._process.wait()
        finally:
            self._stop.set()
            self._server.close()
            if self._auth_thread:
                self._auth_thread.join(timeout=2)
            if self._master is not None:
                os.close(self._master)
                self._master = None
            self._tempdir.cleanup()
        self.on_exit(code)
