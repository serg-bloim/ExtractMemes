"""Diagnostic: download a sample video with yt-dlp through a proxy, to check whether it clears
YouTube's "Sign in to confirm you're not a bot" block seen from the GitHub Actions runner.

Run:

    python download_via_proxy.py

Not part of the extract_memes package -- standalone, talks to yt-dlp directly so proxy behavior is
easy to isolate from the rest of the pipeline.

Two things this script got wrong before, both worth remembering:

1. macOS "Local Network" privacy blocks the LAN proxy, not the proxy itself.
   On macOS Sequoia and later, connecting to a LAN peer needs the Local Network permission, held
   per binary identity rather than inherited from whoever launched you. Apple platform binaries
   (/usr/bin/curl, /usr/bin/nc, /usr/bin/python3) had it; Homebrew's ad-hoc-signed python3.14 and
   node did not -- every connect() to a LAN address failed immediately with EHOSTUNREACH ("No route
   to host"), even though routing and ARP are fine and curl works from the same shell. That is what
   the old "No route to host" was: the local leg to 192.168.1.99 never left this machine. It had
   nothing to do with the proxy's route to YouTube.
   The Python interpreter has since been granted the permission, so PROXY points straight at the
   proxy. If the block returns, the preflight says so, and tools/lan_proxy_relay.py routes around
   it via loopback, which is exempt from the gate. See ADR 017.

2. "socks5h://", not "socks5://" or the non-standard "socks://". The "h" means the proxy resolves
   DNS on its end, matching how a browser configured with the same SOCKS proxy behaves.
   "socks5://" resolves locally first, and local DNS returns YouTube's IPv6 addresses ahead of its
   IPv4 ones; the proxy's exit network has no IPv6 route, so it answers SOCKS5 reply 0x04 ("host
   unreachable"). This is exactly why `curl --socks5` fails against this proxy while
   `curl --socks5-hostname` succeeds. With "socks5h://" the question never arises, so no
   IPv4-forcing workaround (yt-dlp's `source_address` / `--force-ipv4`) is needed.
"""

import errno
import socket
from pathlib import Path

# The proxy itself. If this fails with EHOSTUNREACH on macOS, the preflight below will tell you to
# start tools/lan_proxy_relay.py and switch this to "socks5h://127.0.0.1:1080".
PROXY = "socks5h://vareniki.duckdns.org:5577"

URL = "https://youtu.be/AElGyY97k_0"
DEST_DIR = Path(".runtime") / "proxy_test"
FORMAT = "wv*[ext=mp4]/wv*"  # same "worst" selector downloader.py uses; see ADR 006


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
    import yt_dlp

    if not PROXY:
        raise SystemExit("Set PROXY at the top of this file before running.")
    preflight(PROXY)

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    options = {
        "format": FORMAT,
        "outtmpl": str(DEST_DIR / "%(id)s_worst.%(ext)s"),
        "js_runtimes": {"node": {}},
        "proxy": PROXY,
        "quiet": False,
        "noprogress": False,
        "retries": 10,
        "extractor_retries": 10,
        "socket_timeout": 15,
    }
    print(f"Downloading {URL} via proxy {PROXY!r} ...")
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(URL, download=True)
        path = Path(ydl.prepare_filename(info))

    print(f"\n✓ Success: {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
