"""Loopback HTTP-CONNECT proxy that tunnels through a SOCKS proxy, so ffmpeg can use one.

ffmpeg has no SOCKS support at all, and -- worse than refusing -- it *silently ignores* a SOCKS
proxy and connects straight to the origin, whether the URL arrives as `-http_proxy` or in the
`HTTP_PROXY` environment variable that yt-dlp's ffmpeg downloader sets. Section downloads go
through that downloader, so without this bridge a proxied run would quietly leave the proxy. See
ADR 019.

`serve()` puts an HTTP proxy on loopback that ffmpeg *does* understand and forwards each tunnel
over SOCKS. It answers `CONNECT` and nothing else, so a request can never fall through to a direct
connection.
"""

import socket
import socketserver
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlsplit

SOCKS_SCHEMES = frozenset({"socks", "socks4", "socks4a", "socks5", "socks5h"})
"""Proxy URL schemes that need a bridge. `socks` is yt-dlp's alias for SOCKS4."""

_BUFFER_SIZE = 65536


def is_socks(proxy: str | None) -> bool:
    """Whether `proxy` is a SOCKS URL, and so unusable by ffmpeg directly."""
    if not proxy:
        return False
    return urlsplit(proxy).scheme.lower() in SOCKS_SCHEMES


def _proxy_settings(socks_url: str) -> tuple:
    """Translate a SOCKS URL into the arguments `sockssocket.setproxy` takes."""
    # Imported lazily so importing this module has no side effects (and costs nothing offline).
    from yt_dlp.socks import ProxyType

    parts = urlsplit(socks_url)
    scheme = parts.scheme.lower()
    if scheme not in SOCKS_SCHEMES:
        raise ValueError(f"not a SOCKS proxy URL: {socks_url!r}")
    if not parts.hostname:
        raise ValueError(f"SOCKS proxy URL has no host: {socks_url!r}")
    proxy_type = {
        "socks": ProxyType.SOCKS4,
        "socks4": ProxyType.SOCKS4,
        "socks4a": ProxyType.SOCKS4A,
        "socks5": ProxyType.SOCKS5,
        "socks5h": ProxyType.SOCKS5,
    }[scheme]
    # The trailing "h" is what asks the proxy to resolve the hostname itself, which is the whole
    # point of socks5h:// here -- see ADR 017 on why local resolution breaks against this proxy.
    rdns = scheme in ("socks4a", "socks5h")
    port = parts.port or 1080
    return proxy_type, parts.hostname, port, rdns, parts.username, parts.password


def _pump(source: socket.socket, sink: socket.socket) -> None:
    """Copy bytes one way until the source ends or either side goes away."""
    try:
        while chunk := source.recv(_BUFFER_SIZE):
            sink.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            sink.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _make_handler(socks_url: str) -> type[socketserver.BaseRequestHandler]:
    class ConnectHandler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            request_line = self.rfile.readline(4096).decode("latin-1").strip()
            parts = request_line.split()
            if len(parts) < 2 or parts[0].upper() != "CONNECT":
                # Only tunnels are forwarded. Refusing everything else is what keeps a request
                # from silently going direct if ffmpeg ever asks for something we don't proxy.
                self._respond(501, "Not Implemented")
                return
            while (header := self.rfile.readline(65536)) not in (b"\r\n", b"\n", b""):
                pass
            host, _, port = parts[1].rpartition(":")
            try:
                upstream = self._connect(host, int(port))
            except (OSError, ValueError) as exc:
                print(f"socks bridge: CONNECT {parts[1]} failed: {exc}")
                self._respond(502, "Bad Gateway")
                return
            try:
                self._respond(200, "Connection established")
                outbound = threading.Thread(
                    target=_pump, args=(self.connection, upstream), daemon=True
                )
                outbound.start()
                _pump(upstream, self.connection)
                outbound.join()
            finally:
                upstream.close()

        def _connect(self, host: str, port: int) -> socket.socket:
            from yt_dlp.socks import sockssocket

            upstream = sockssocket()
            try:
                upstream.setproxy(*_proxy_settings(socks_url))
                upstream.connect((host, port))
            except Exception:
                upstream.close()
                raise
            return upstream

        def _respond(self, status: int, reason: str) -> None:
            self.wfile.write(f"HTTP/1.1 {status} {reason}\r\n\r\n".encode("latin-1"))
            self.wfile.flush()

        def handle_error(self, *args) -> None:  # pragma: no cover - server-side logging only
            pass

    return ConnectHandler


class _BridgeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:  # pragma: no cover
        """A client hanging up mid-tunnel is normal; don't print a traceback for it."""


@contextmanager
def serve(socks_url: str) -> Iterator[str]:
    """Run a loopback HTTP proxy tunnelling through `socks_url`; yield its `http://` URL.

    The server listens on an ephemeral port for the life of the `with` block, handling each
    `CONNECT` on its own thread. `socks_url` is validated up front, so a malformed one raises here
    rather than turning into a failed tunnel later.
    """
    _proxy_settings(socks_url)
    server = _BridgeServer(("127.0.0.1", 0), _make_handler(socks_url))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
