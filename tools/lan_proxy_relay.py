#!/usr/bin/env /usr/bin/python3
"""Loopback -> LAN TCP relay, so third-party interpreters can reach a LAN proxy on macOS.

Why this exists
---------------
macOS (Sequoia and later) gates connections to LAN peers behind the "Local Network" privacy
permission. Apple-signed platform binaries (/usr/bin/curl, /usr/bin/nc, /usr/bin/python3) inherit
the grant held by the terminal app that launched them. Homebrew's python3.14 and node are
*ad-hoc signed*, so they get their own TCC identity, which was never granted -- every connect() to
a LAN address fails instantly with EHOSTUNREACH ("No route to host"), even though routing and ARP
are fine and curl works from the same shell.

Loopback (127.0.0.1) is exempt from that gate. So: run this relay under Apple's platform-signed
/usr/bin/python3 (hence the shebang), point it at the LAN proxy, and let the project's venv Python
talk to 127.0.0.1 instead.

Usage:
    ./tools/lan_proxy_relay.py                       # 127.0.0.1:1080 -> 192.168.1.99:25344
    ./tools/lan_proxy_relay.py --listen 127.0.0.1:1080 --target 192.168.1.99:25344

Then give any client socks5h://127.0.0.1:1080 as its proxy.
"""

import argparse
import asyncio
import sys

DEFAULT_LISTEN = "127.0.0.1:1080"
DEFAULT_TARGET = "192.168.1.99:25344"


def split_hostport(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        raise argparse.ArgumentTypeError(f"expected host:port, got {value!r}")
    return host, int(port)


async def pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, TimeoutError):
        pass
    finally:
        writer.close()


def make_handler(target_host: str, target_port: int):
    async def handle(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        try:
            server_reader, server_writer = await asyncio.open_connection(target_host, target_port)
        except OSError as exc:
            print(f"  upstream connect failed: {exc}", file=sys.stderr, flush=True)
            client_writer.close()
            return
        await asyncio.gather(
            pump(client_reader, server_writer),
            pump(server_reader, client_writer),
        )

    return handle


async def main_async(args: argparse.Namespace) -> None:
    listen_host, listen_port = args.listen
    target_host, target_port = args.target
    server = await asyncio.start_server(
        make_handler(target_host, target_port), listen_host, listen_port
    )
    print(
        f"relaying {listen_host}:{listen_port} -> {target_host}:{target_port}  (ctrl-c to stop)",
        flush=True,
    )
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--listen", type=split_hostport, default=split_hostport(DEFAULT_LISTEN))
    parser.add_argument("--target", type=split_hostport, default=split_hostport(DEFAULT_TARGET))
    args = parser.parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nstopped", flush=True)


if __name__ == "__main__":
    main()
