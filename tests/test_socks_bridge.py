import socket
import socketserver
import threading

import pytest

from extract_memes import socks_bridge
from extract_memes.socks_bridge import is_socks, serve


@pytest.mark.parametrize(
    ("proxy", "expected"),
    [
        (None, False),
        ("", False),
        ("socks5h://127.0.0.1:1080", True),
        ("socks5://127.0.0.1:1080", True),
        ("socks4a://127.0.0.1:1080", True),
        ("socks4://127.0.0.1:1080", True),
        ("SOCKS5H://127.0.0.1:1080", True),
        ("socks://127.0.0.1:1080", True),
        ("http://127.0.0.1:3128", False),
        ("https://proxy.example:8080", False),
    ],
)
def test_is_socks(proxy, expected):
    assert is_socks(proxy) is expected


@pytest.mark.parametrize(
    ("url", "expected_rdns"),
    [("socks5h://host:1080", True), ("socks5://host:1080", False), ("socks4a://host:1080", True)],
)
def test_proxy_settings_reads_the_scheme(url, expected_rdns):
    from yt_dlp.socks import ProxyType

    proxy_type, host, port, rdns, username, password = socks_bridge._proxy_settings(url)

    assert proxy_type in (ProxyType.SOCKS4, ProxyType.SOCKS4A, ProxyType.SOCKS5)
    assert (host, port, rdns) == ("host", 1080, expected_rdns)
    assert (username, password) == (None, None)


def test_proxy_settings_carries_credentials_and_the_default_port():
    _, host, port, _, username, password = socks_bridge._proxy_settings("socks5h://bob:s3cret@host")

    assert (host, port, username, password) == ("host", 1080, "bob", "s3cret")


@pytest.mark.parametrize("url", ["http://host:3128", "socks5h://"])
def test_serve_rejects_a_url_it_cannot_tunnel(url):
    with pytest.raises(ValueError):
        with serve(url):
            pass


class _EchoServer(socketserver.ThreadingTCPServer):
    """Stands in for whatever the tunnel is pointed at."""

    allow_reuse_address = True
    daemon_threads = True

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            while chunk := self.request.recv(4096):
                self.request.sendall(chunk.upper())


class _StubSocks5Server(socketserver.ThreadingTCPServer):
    """A SOCKS5 proxy that only knows how to reach one address: `target`."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, target: tuple[str, int]):
        self.target = target
        self.requested: list[tuple[str, int]] = []
        super().__init__(("127.0.0.1", 0), self.Handler)

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            version, method_count = self.request.recv(2)
            self.request.recv(method_count)
            assert version == 5
            self.request.sendall(b"\x05\x00")  # version 5, no authentication
            header = self.request.recv(4)
            address_type = header[3]
            if address_type == 3:  # a hostname, i.e. the proxy resolves it (socks5h)
                length = self.request.recv(1)[0]
                host = self.request.recv(length).decode()
            else:
                host = socket.inet_ntoa(self.request.recv(4))
            port = int.from_bytes(self.request.recv(2), "big")
            self.server.requested.append((host, port))
            upstream = socket.create_connection(self.server.target)
            self.request.sendall(b"\x05\x00\x00\x01" + b"\x00" * 6)
            threading.Thread(
                target=socks_bridge._pump, args=(self.request, upstream), daemon=True
            ).start()
            socks_bridge._pump(upstream, self.request)
            upstream.close()


@pytest.fixture
def socks_proxy():
    """A stub SOCKS5 proxy in front of an echo server; yields (proxy url, proxy server)."""
    echo = _EchoServer(("127.0.0.1", 0), _EchoServer.Handler)
    proxy = _StubSocks5Server(echo.server_address[:2])
    for server in (echo, proxy):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        host, port = proxy.server_address[:2]
        yield f"socks5h://{host}:{port}", proxy
    finally:
        for server in (echo, proxy):
            server.shutdown()
            server.server_close()


def _request(bridge_url: str, request: bytes) -> tuple[bytes, socket.socket]:
    """Send `request` to the bridge; return its response line and the still-open socket."""
    host, _, port = bridge_url.removeprefix("http://").rpartition(":")
    client = socket.create_connection((host, int(port)), timeout=5)
    client.sendall(request)
    return client.recv(4096).split(b"\r\n")[0], client


def test_connect_tunnels_through_the_socks_proxy(socks_proxy):
    proxy_url, proxy = socks_proxy

    with serve(proxy_url) as bridge_url:
        assert bridge_url.startswith("http://127.0.0.1:")
        status, client = _request(bridge_url, b"CONNECT media.example:443 HTTP/1.1\r\n\r\n")
        try:
            assert status == b"HTTP/1.1 200 Connection established"
            client.sendall(b"hello")
            assert client.recv(4096) == b"HELLO"
        finally:
            client.close()

    # The hostname went to the proxy unresolved, which is what socks5h:// is for.
    assert proxy.requested == [("media.example", 443)]


def test_anything_other_than_connect_is_refused(socks_proxy):
    proxy_url, proxy = socks_proxy

    with serve(proxy_url) as bridge_url:
        status, client = _request(bridge_url, b"GET http://media.example/x HTTP/1.1\r\n\r\n")
        client.close()

    assert status == b"HTTP/1.1 501 Not Implemented"
    assert proxy.requested == []


def test_an_unreachable_socks_proxy_is_a_bad_gateway():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]

    with serve(f"socks5h://127.0.0.1:{dead_port}") as bridge_url:
        status, client = _request(bridge_url, b"CONNECT media.example:443 HTTP/1.1\r\n\r\n")
        client.close()

    assert status == b"HTTP/1.1 502 Bad Gateway"
