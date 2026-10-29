#!/usr/bin/python3
"""Give the child a controlling PTY without a preexec hook in the GTK process."""

import fcntl
import os
import sys
import termios


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(2)
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    os.execvpe(sys.argv[1], sys.argv[1:], os.environ)
