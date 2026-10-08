"""The addresses the labeler can be opened at: `python -m tools.labeling.network PORT` prints them."""

import socket
import sys


def lan_address() -> str | None:
    """This machine's address on the local network (the one its default route uses), or None."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))  # a UDP "connect" sends nothing; it only picks the route
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return None if address.startswith("127.") else address


def urls(port: int) -> list[str]:
    """The page's address on this machine and, when there is one, on the local network."""
    found = [f"http://127.0.0.1:{port}/"]
    if address := lan_address():
        found.append(f"http://{address}:{port}/")
    return found


def announce(port: int) -> str:
    local, *network = urls(port)
    line = f"Labeler: {local}"
    if network:
        line += f"  |  on your network: {network[0]}  (no login: anyone on this network can open it)"
    return line


if __name__ == "__main__":
    print(announce(int(sys.argv[1])))
