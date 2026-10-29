#!/usr/bin/python3
"""Bridge sudo's askpass protocol to the running Central window."""

import json
import os
import socket
import sys


def main():
    path = os.environ.get("ARCH_UPDATE_ASKPASS_SOCKET")
    if not path:
        return 1
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(path)
            client.sendall(b"arch-update-askpass\n")
            chunks = bytearray()
            while b"\n" not in chunks and len(chunks) < 65536:
                data = client.recv(4096)
                if not data:
                    return 1
                chunks.extend(data)
        response = json.loads(bytes(chunks).split(b"\n", 1)[0].decode("utf-8"))
        password = response.get("password")
        if not isinstance(password, str) or "\n" in password or "\r" in password:
            return 1
        sys.stdout.write(password + "\n")
        sys.stdout.flush()
        return 0
    except (OSError, ValueError, TypeError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
