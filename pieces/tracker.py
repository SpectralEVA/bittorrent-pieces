import socket
import struct
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote_from_bytes
from urllib.request import Request, urlopen

from pieces.bencoding import Decoder

DEFAULT_ANNOUNCE_INTERVAL = 300


@dataclass(frozen=True, slots=True)
class Peer:
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class AnnounceResult:
    peers: list[Peer]
    interval: int = DEFAULT_ANNOUNCE_INTERVAL


def _parse_compact_peers(peers: bytes) -> list[Peer]:
    if len(peers) % 6 != 0:
        raise ValueError("Compact peers data length must be a multiple of 6 bytes.")

    result: list[Peer] = []
    for offset in range(0, len(peers), 6):
        chunk = peers[offset : offset + 6]
        host = socket.inet_ntoa(chunk[:4])
        port = struct.unpack("!H", chunk[4:6])[0]
        result.append(Peer(host=host, port=port))
    return result


def _decode_tracker_response(data: bytes) -> AnnounceResult:
    decoded = Decoder(data).decode()
    if not isinstance(decoded, dict):
        raise ValueError("Tracker response must be a bencoded dictionary.")

    if b"failure reason" in decoded:
        reason = decoded[b"failure reason"]
        if isinstance(reason, bytes):
            message = reason.decode("utf-8", errors="replace")
        else:
            message = str(reason)
        raise RuntimeError(message)

    peers = decoded.get(b"peers", b"")
    if not isinstance(peers, bytes):
        raise ValueError("Tracker peers field must be a compact byte string.")

    interval_raw = decoded.get(b"interval", DEFAULT_ANNOUNCE_INTERVAL)
    interval = int(interval_raw) if isinstance(interval_raw, int) else DEFAULT_ANNOUNCE_INTERVAL

    return AnnounceResult(peers=_parse_compact_peers(peers), interval=interval)


def announce(
    tracker_url: str,
    info_hash: bytes,
    peer_id: bytes,
    port: int,
    left: int,
    uploaded: int = 0,
    downloaded: int = 0,
    event: str | None = "started",
) -> AnnounceResult:
    encoded_hash = quote_from_bytes(info_hash)
    encoded_peer_id = quote_from_bytes(peer_id)
    url = (
        f"{tracker_url}?info_hash={encoded_hash}"
        f"&peer_id={encoded_peer_id}"
        f"&port={port}"
        f"&uploaded={uploaded}"
        f"&downloaded={downloaded}"
        f"&left={left}"
        f"&compact=1"
    )
    if event is not None:
        url += f"&event={event}"

    request = Request(url, method="GET")

    try:
        with urlopen(request, timeout=30) as response:
            data = response.read()
    except HTTPError as exc:
        raise RuntimeError(f"Tracker announce failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"Tracker announce failed: {exc.reason}") from exc

    return _decode_tracker_response(data)
