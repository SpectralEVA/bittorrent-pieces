import socket
import struct
from dataclasses import dataclass

PROTOCOL_STRING = b"BitTorrent protocol"
HANDSHAKE_LENGTH = 68
INFO_HASH_OFFSET = 1 + len(PROTOCOL_STRING) + 8
INFO_HASH_LENGTH = 20


@dataclass(frozen=True, slots=True)
class Message:
    id: int | None
    payload: bytes


def _build_handshake(info_hash: bytes, peer_id: bytes) -> bytes:
    return (
        bytes([len(PROTOCOL_STRING)])
        + PROTOCOL_STRING
        + b"\x00" * 8
        + info_hash
        + peer_id
    )


class PeerConnection:
    def __init__(self) -> None:
        self.socket: socket.socket | None = None

    def connect(
        self,
        host: str,
        port: int,
        info_hash: bytes,
        peer_id: bytes,
        timeout: float = 5.0,
    ) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        self.socket = sock

        self.socket.sendall(_build_handshake(info_hash, peer_id))

        response = self._read_exact(HANDSHAKE_LENGTH)
        received_hash = response[INFO_HASH_OFFSET : INFO_HASH_OFFSET + INFO_HASH_LENGTH]
        if received_hash != info_hash:
            self.socket.close()
            self.socket = None
            raise ValueError("Peer info_hash does not match expected info_hash")

    def _read_exact(self, n: int) -> bytes:
        if self.socket is None:
            raise ConnectionError("Socket is not connected.")

        buffer = bytearray()
        while len(buffer) < n:
            chunk = self.socket.recv(n - len(buffer))
            if not chunk:
                raise ConnectionError("Peer disconnected unexpectedly")
            buffer.extend(chunk)
        return bytes(buffer)

    def read_message(self) -> Message:
        length = struct.unpack(">I", self._read_exact(4))[0]
        if length == 0:
            return Message(id=None, payload=b"")

        message_id = self._read_exact(1)[0]
        payload = self._read_exact(length - 1) if length > 1 else b""
        return Message(id=message_id, payload=payload)

    def send_interested(self) -> None:
        if self.socket is None:
            raise ConnectionError("Socket is not connected.")
        self.socket.sendall(struct.pack(">IB", 1, 2))

    def send_request(self, index: int, begin: int, length: int) -> None:
        if self.socket is None:
            raise ConnectionError("Socket is not connected.")
        self.socket.sendall(
            struct.pack(">IB", 13, 6) + struct.pack(">III", index, begin, length)
        )
