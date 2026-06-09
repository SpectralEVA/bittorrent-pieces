import socket
import struct
from unittest.mock import MagicMock, patch

import pytest

from pieces.protocol import (
    HANDSHAKE_LENGTH,
    Message,
    PeerConnection,
    _build_handshake,
)


class MockSocket:
    """Simulates a TCP socket with scripted ``recv`` chunks and captured ``sendall`` data."""

    def __init__(self, recv_chunks: list[bytes]) -> None:
        self.sent: list[bytes] = []
        self._recv_chunks = list(recv_chunks)
        self._recv_index = 0
        self._recv_offset = 0
        self.closed = False

    def connect(self, address: tuple[str, int]) -> None:
        self.address = address

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, bufsize: int) -> bytes:
        if self._recv_index >= len(self._recv_chunks):
            return b""

        current = self._recv_chunks[self._recv_index]
        available = current[self._recv_offset :]
        chunk = available[:bufsize]

        self._recv_offset += len(chunk)
        if self._recv_offset >= len(current):
            self._recv_index += 1
            self._recv_offset = 0

        return chunk

    def close(self) -> None:
        self.closed = True


def test_connect_sends_and_validates_handshake() -> None:
    info_hash = b"\xaa" * 20
    peer_id = b"\xbb" * 20
    peer_handshake = _build_handshake(info_hash, b"\xcc" * 20)

    mock_sock = MockSocket([peer_handshake])

    with patch("pieces.protocol.socket.socket", return_value=mock_sock):
        connection = PeerConnection()
        connection.connect("127.0.0.1", 6881, info_hash, peer_id, timeout=3.0)

    assert mock_sock.address == ("127.0.0.1", 6881)
    assert mock_sock.timeout == 3.0
    assert len(mock_sock.sent) == 1
    assert mock_sock.sent[0] == _build_handshake(info_hash, peer_id)
    assert len(mock_sock.sent[0]) == HANDSHAKE_LENGTH
    assert connection.socket is mock_sock


def test_connect_rejects_mismatched_info_hash() -> None:
    info_hash = b"\xaa" * 20
    peer_id = b"\xbb" * 20
    wrong_hash = b"\xff" * 20
    peer_handshake = _build_handshake(wrong_hash, b"\xcc" * 20)

    mock_sock = MockSocket([peer_handshake])

    with patch("pieces.protocol.socket.socket", return_value=mock_sock):
        connection = PeerConnection()
        with pytest.raises(ValueError, match="info_hash"):
            connection.connect("127.0.0.1", 6881, info_hash, peer_id)

    assert mock_sock.closed is True
    assert connection.socket is None


def test_read_message_decodes_length_prefixed_messages() -> None:
    info_hash = b"\xaa" * 20
    peer_id = b"\xbb" * 20
    peer_handshake = _build_handshake(info_hash, b"\xcc" * 20)

    unchoke = struct.pack(">IB", 1, 1)
    bitfield_payload = b"\xff\x00"
    bitfield = struct.pack(">I", 1 + len(bitfield_payload)) + bytes([5]) + bitfield_payload
    keep_alive = struct.pack(">I", 0)

    mock_sock = MockSocket([peer_handshake, unchoke + bitfield + keep_alive])

    with patch("pieces.protocol.socket.socket", return_value=mock_sock):
        connection = PeerConnection()
        connection.connect("127.0.0.1", 6881, info_hash, peer_id)

    assert connection.read_message() == Message(id=1, payload=b"")
    assert connection.read_message() == Message(id=5, payload=bitfield_payload)
    assert connection.read_message() == Message(id=None, payload=b"")


def test_read_exact_handles_fragmented_recv() -> None:
    mock_sock = MockSocket([b"ab", b"cd"])
    connection = PeerConnection()
    connection.socket = mock_sock

    assert connection._read_exact(4) == b"abcd"


def test_send_interested_and_send_request() -> None:
    mock_sock = MockSocket([])
    connection = PeerConnection()
    connection.socket = mock_sock

    connection.send_interested()
    connection.send_request(index=3, begin=16384, length=16384)

    assert mock_sock.sent[0] == struct.pack(">IB", 1, 2)
    assert mock_sock.sent[1] == (
        struct.pack(">IB", 13, 6) + struct.pack(">III", 3, 16384, 16384)
    )


def test_read_exact_raises_on_early_disconnect() -> None:
    mock_sock = MagicMock(spec=socket.socket)
    mock_sock.recv.side_effect = [b"ab", b""]

    connection = PeerConnection()
    connection.socket = mock_sock

    with pytest.raises(ConnectionError, match="Peer disconnected unexpectedly"):
        connection._read_exact(4)
