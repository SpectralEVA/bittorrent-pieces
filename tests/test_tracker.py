import socket
import struct
from io import BytesIO
from unittest.mock import patch

import pytest

from pieces.bencoding import encode
from pieces.tracker import Peer, _decode_tracker_response, announce


def _compact_peer(ip: str, port: int) -> bytes:
    return socket.inet_aton(ip) + struct.pack("!H", port)


def test_compact_peer_parsing() -> None:
    peers = (
        _compact_peer("192.168.1.1", 6881)
        + _compact_peer("10.0.0.5", 51413)
    )
    response = encode({b"interval": 1800, b"peers": peers})

    parsed = _decode_tracker_response(response)

    assert parsed == [
        Peer(host="192.168.1.1", port=6881),
        Peer(host="10.0.0.5", port=51413),
    ]

    with patch("pieces.tracker.urlopen") as mock_urlopen:
        mock_urlopen.return_value = BytesIO(response)

        result = announce(
            tracker_url="http://tracker.example.com/announce",
            info_hash=b"\xab" * 20,
            peer_id=b"\xcd" * 20,
            port=6881,
            left=1024,
        )

    assert result == parsed
    called_url = mock_urlopen.call_args[0][0].full_url
    assert called_url.startswith("http://tracker.example.com/announce?")
    assert "info_hash=" in called_url
    assert "peer_id=" in called_url
    assert "compact=1" in called_url
    assert "event=started" in called_url


def test_tracker_failure_reason_raises_runtime_error() -> None:
    response = encode({b"failure reason": b"Invalid info_hash"})

    with pytest.raises(RuntimeError, match="Invalid info_hash"):
        _decode_tracker_response(response)

    with patch("pieces.tracker.urlopen") as mock_urlopen:
        mock_urlopen.return_value = BytesIO(response)

        with pytest.raises(RuntimeError, match="Invalid info_hash"):
            announce(
                tracker_url="http://tracker.example.com/announce",
                info_hash=b"\x01" * 20,
                peer_id=b"\x02" * 20,
                port=6881,
                left=0,
            )
