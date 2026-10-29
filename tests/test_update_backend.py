import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from update_backend import UpdateSession


FAKE_YAY = r'''import os, subprocess, sys
if not os.isatty(0) or os.getsid(0) != os.getpid():
    sys.exit(30)
print("Proceed? [Y/n] ", end="", flush=True)
if input().strip() != "y":
    sys.exit(31)
result = subprocess.run([os.environ["SUDO_ASKPASS"], "Password:"], capture_output=True, text=True)
if result.returncode != 0:
    print("Authentication cancelled", flush=True)
    sys.exit(42)
if result.stdout != "test-only-credential\n":
    sys.exit(43)
print("Update completed", flush=True)
'''


class UpdateSessionTests(unittest.TestCase):
    def run_fake(self, password):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "fake_yay.py"
            fake.write_text(FAKE_YAY)
            prompt = threading.Event()
            finished = threading.Event()
            output = []
            result = []
            socket_modes = []

            def on_output(text):
                output.append(text)
                if "Proceed?" in "".join(output):
                    prompt.set()

            def on_authentication(request):
                socket_modes.append(stat.S_IMODE(os.stat(session._server.getsockname()).st_mode))
                request.respond(password)

            session = UpdateSession([sys.executable, str(fake)], on_output, on_authentication,
                                    lambda code: (result.append(code), finished.set()))
            session.start()
            self.assertTrue(prompt.wait(10), "the child did not show its prompt")
            self.assertTrue(session.send_response("y"))
            self.assertTrue(finished.wait(15), "the child did not finish")
            return result[0], "".join(output), socket_modes

    def test_interactive_update_and_password_do_not_echo_secret(self):
        code, output, socket_modes = self.run_fake("test-only-credential")
        self.assertEqual(code, 0)
        self.assertIn("Update completed", output)
        self.assertNotIn("test-only-credential", output)
        self.assertEqual(socket_modes, [0o600])

    def test_cancelling_authentication_stops_the_child(self):
        code, output, _ = self.run_fake(None)
        self.assertEqual(code, 42)
        self.assertIn("Authentication cancelled", output)

    def test_secret_response_is_not_echoed_even_if_child_enabled_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "fake_prompt.py"
            fake.write_text(
                "import sys,termios\n"
                "a=termios.tcgetattr(0); a[3] |= termios.ECHO; termios.tcsetattr(0,termios.TCSANOW,a)\n"
                "print('Passphrase: ',end='',flush=True)\n"
                "sys.exit(0 if input() == 'test-only-secret' else 1)\n"
            )
            prompt = threading.Event()
            finished = threading.Event()
            output = []
            result = []

            def on_output(text):
                output.append(text)
                if "Passphrase:" in "".join(output):
                    prompt.set()

            session = UpdateSession([sys.executable, str(fake)], on_output, lambda request: request.respond(None),
                                    lambda code: (result.append(code), finished.set()))
            session.start()
            self.assertTrue(prompt.wait(10))
            self.assertTrue(session.send_response("test-only-secret", secret=True))
            self.assertTrue(finished.wait(10))
            self.assertEqual(result, [0])
            self.assertNotIn("test-only-secret", "".join(output))


if __name__ == "__main__":
    unittest.main()
