import os
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from pieces.bencoding import Decoder
from pieces.pieces_manager import PieceManager
from pieces.protocol import PeerConnection
from pieces.torrent import Torrent
from pieces.tracker import Peer, announce

PEER_ID_PREFIX = b"-PC0001-"
_PROGRESS_LOCK = threading.Lock()


def load_torrent(torrent_path: str) -> Torrent:
    with open(torrent_path, "rb") as file:
        return Torrent(Decoder(file.read()).decode())


def generate_peer_id() -> bytes:
    suffix_length = 20 - len(PEER_ID_PREFIX)
    return PEER_ID_PREFIX + os.urandom(suffix_length)


def _parse_piece_payload(payload: bytes) -> tuple[int, int, bytes]:
    if len(payload) < 8:
        raise ValueError("PIECE message payload is too short.")
    piece_index, begin = struct.unpack(">II", payload[:8])
    return piece_index, begin, payload[8:]


def _print_progress(manager: PieceManager) -> None:
    with _PROGRESS_LOCK:
        completed = manager.completed_piece_count()
        total = manager.torrent.num_pieces
        percent = int((completed / total) * 100) if total else 100
        print(f"Downloading: Piece {completed}/{total} ({percent}%) Complete...")


def _request_next_block(connection: PeerConnection, manager: PieceManager) -> bool:
    request = manager.next_request()
    if request is None:
        return False

    piece_index, begin, length = request
    connection.send_request(piece_index, begin, length)
    return True


def _download_from_peer(
    peer: Peer,
    torrent: Torrent,
    info_hash: bytes,
    my_peer_id: bytes,
    piece_manager: PieceManager,
) -> None:
    if piece_manager.is_complete:
        return

    connection = PeerConnection()
    try:
        print(f"Connecting to peer {peer.host}:{peer.port}...")
        connection.connect(peer.host, peer.port, info_hash, my_peer_id)
        connection.send_interested()
        peer_choking = True

        while not piece_manager.is_complete:
            if not peer_choking:
                _request_next_block(connection, piece_manager)

            message = connection.read_message()
            if message.id is None:
                continue

            if message.id == 0:
                peer_choking = True
            elif message.id == 1:
                peer_choking = False
                _request_next_block(connection, piece_manager)
            elif message.id == 7:
                piece_index, begin, block_data = _parse_piece_payload(message.payload)
                if piece_manager.handle_block(piece_index, begin, block_data):
                    _print_progress(piece_manager)

                if not peer_choking:
                    _request_next_block(connection, piece_manager)

    except (ConnectionError, OSError, ValueError) as exc:
        print(f"Peer {peer.host}:{peer.port} disconnected: {exc}")
    finally:
        if connection.socket is not None:
            connection.socket.close()
            connection.socket = None


def download(torrent_path: str, output_path: str) -> None:
    torrent = load_torrent(torrent_path)
    info_hash = torrent.info_hash
    peer_id = generate_peer_id()
    peers = announce(
        torrent.announce,
        info_hash,
        peer_id,
        port=6881,
        left=torrent.total_length,
    )

    if not peers:
        raise RuntimeError("Tracker returned no peers.")

    manager = PieceManager(torrent, output_path)
    destination = "directory" if torrent.is_multi_file else "file"
    print(f"Starting download: {torrent.name}")
    print(f"Output {destination}: {output_path}")
    print(f"Tracker returned {len(peers)} peer(s). Spawning concurrent workers...")

    with ThreadPoolExecutor(max_workers=len(peers)) as executor:
        futures = [
            executor.submit(
                _download_from_peer,
                peer,
                torrent,
                info_hash,
                peer_id,
                manager,
            )
            for peer in peers
        ]

        while not manager.is_complete:
            time.sleep(0.1)

        for future in futures:
            future.result()

    if not manager.is_complete:
        raise RuntimeError("Failed to download all pieces from available peers.")

    print(f"Download complete: {output_path}")
