"""Diagnostic: fetch a page through the proxy using httpx, i.e. a SOCKS stack unrelated to
yt-dlp's.

httpx's SOCKS support goes through `socksio`; yt-dlp implements SOCKS itself in `yt_dlp/socks.py`.
Running both tells you whether a failure is in one library or in the proxy path they share.

Requires: pip install "httpx[socks]"

Run:
    python fetch_via_httpx.py

The failure this script was originally chasing -- ConnectError('[Errno 65] No route to host') on
every attempt -- was never about the proxy's route to the target. It was macOS "Local Network"
privacy: on Sequoia and later, connecting to a LAN peer needs that permission, and it is held per
binary identity rather than inherited from whoever launched you. Apple platform binaries
(/usr/bin/curl, /usr/bin/nc, /usr/bin/python3) had it; Homebrew's ad-hoc-signed python3.14 and node
did not, so every connect() to 192.168.1.99 failed instantly with EHOSTUNREACH while curl succeeded
from the same shell.

The Python interpreter has since been granted that permission, so PROXY below points straight at
the proxy. If the block returns, the preflight says so, and tools/lan_proxy_relay.py routes around
it via loopback, which is exempt from the gate. See ADR 017.

Note also "socks5h://", not "socks5://": the "h" gives the proxy the hostname and lets it resolve.
Resolving locally hands the proxy YouTube's IPv6 address, which its exit network cannot route
(SOCKS5 reply 0x04) -- the same reason `curl --socks5` fails here while `--socks5-hostname` works.
With socks5h there is no local resolution, so no IPv4-forcing `local_address` workaround is needed.
"""

import errno
import socket

# The proxy itself. If this fails with EHOSTUNREACH on macOS, the preflight below will tell you to
# start tools/lan_proxy_relay.py and switch this to "socks5h://127.0.0.1:1080".
PROXY = "socks5h://192.168.1.99:25344"

URL = "https://www.youtube.com"
ATTEMPTS = 5


def preflight(proxy: str) -> None:
    """Fail loudly, and with the real reason, if we cannot even reach the proxy port."""
    host, _, port = proxy.rsplit("/", 1)[-1].rpartition(":")
    with socket.socket() as probe:
        probe.settimeout(5)
        try:
            probe.connect((host, int(port)))
        except OSError as exc:
            hint = ""
            if exc.errno == errno.EHOSTUNREACH and not host.startswith("127."):
                hint = (
                    "\nEHOSTUNREACH to a LAN address from a Homebrew interpreter is the macOS "
                    "Local Network block (see this file's docstring).\nStart the relay with "
                    "`./tools/lan_proxy_relay.py &` and set PROXY to socks5h://127.0.0.1:1080."
                )
            raise SystemExit(f"Cannot reach proxy {host}:{port} -- {exc}{hint}")


def main() -> None:
    import httpx

    if not PROXY:
        raise SystemExit("Set PROXY at the top of this file before running.")
    preflight(PROXY)

    print(f"Fetching {URL} via proxy {PROXY!r} (httpx/socksio), {ATTEMPTS} attempts ...\n")
    successes = 0
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with httpx.Client(proxy=PROXY, timeout=15.0) as client:
                response = client.get(URL)
            print(f"  attempt {attempt}: OK — HTTP {response.status_code}, {len(response.content):,} bytes")
            successes += 1
        except Exception as exc:
            print(f"  attempt {attempt}: FAILED — {exc!r}")

    print(f"\n{successes}/{ATTEMPTS} succeeded")


if __name__ == "__main__":
    main()
