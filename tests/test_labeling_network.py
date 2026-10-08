import socket

import pytest

pytest.importorskip("yaml")

from tools.labeling import network


def test_the_addresses_include_loopback_first_and_the_lan_address_when_there_is_one(monkeypatch):
    monkeypatch.setattr(network, "lan_address", lambda: "192.168.1.208")
    assert network.urls(8765) == ["http://127.0.0.1:8765/", "http://192.168.1.208:8765/"]
    assert "http://192.168.1.208:8765/" in network.announce(8765) and "no login" in network.announce(8765)

    monkeypatch.setattr(network, "lan_address", lambda: None)
    assert network.urls(8765) == ["http://127.0.0.1:8765/"]
    assert "network" not in network.announce(8765)


def test_the_lan_address_is_an_ipv4_address_that_is_not_loopback():
    address = network.lan_address()

    assert address is None or (socket.inet_aton(address) and not address.startswith("127."))
