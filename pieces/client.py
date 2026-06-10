import os
import struct
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

from pieces.bencoding import Decoder
from pieces.pieces_manager import PieceManager
from pieces.protocol import PeerConnection
from pieces.torrent import Torrent
from pieces.tracker import AnnounceResult, Peer, announce

PEER_ID_PREFIX = b"-PC0001-"
MIN_ACTIVE_PEERS = 5
REANNOUNCE_COOLDOWN_SECONDS = 60
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


class PeerPool:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_count = 0
        self._connected: set[tuple[str, int]] = set()
        self._failed: set[tuple[str, int]] = set()

    @staticmethod
    def key(peer: Peer) -> tuple[str, int]:
        return (peer.host, peer.port)

    def register_connected(self, peer: Peer) -> None:
        with self._lock:
            self._connected.add(self.key(peer))
            self._active_count += 1

    def unregister_connected(self, peer: Peer) -> None:
        with self._lock:
            self._connected.discard(self.key(peer))
            self._active_count = max(0, self._active_count - 1)

    def mark_failed(self, peer: Peer) -> None:
        with self._lock:
            self._failed.add(self.key(peer))

    def active_count(self) -> int:
        with self._lock:
            return self._active_count

    def filter_new_peers(self, peers: list[Peer]) -> list[Peer]:
        with self._lock:
            return [
                peer
                for peer in peers
                if self.key(peer) not in self._connected
                and self.key(peer) not in self._failed
            ]

    def prepare_reannounce(self) -> None:
        with self._lock:
            self._failed.clear()


def _download_from_peer(
    peer: Peer,
    torrent: Torrent,
    info_hash: bytes,
    my_peer_id: bytes,
    piece_manager: PieceManager,
    peer_pool: PeerPool,
) -> None:
    if piece_manager.is_complete:
        return

    connection = PeerConnection()
    connected_registered = False
    try:
        print(f"Connecting to peer {peer.host}:{peer.port}...")
        connection.connect(peer.host, peer.port, info_hash, my_peer_id)
        peer_pool.register_connected(peer)
        connected_registered = True
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
        peer_pool.mark_failed(peer)
    finally:
        if connected_registered:
            peer_pool.unregister_connected(peer)
        if connection.socket is not None:
            connection.socket.close()
            connection.socket = None


def _spawn_peer_workers(
    executor: ThreadPoolExecutor,
    peers: list[Peer],
    torrent: Torrent,
    info_hash: bytes,
    peer_id: bytes,
    manager: PieceManager,
    peer_pool: PeerPool,
    futures: set[Future[None]],
) -> int:
    spawned = 0
    for peer in peer_pool.filter_new_peers(peers):
        future = executor.submit(
            _download_from_peer,
            peer,
            torrent,
            info_hash,
            peer_id,
            manager,
            peer_pool,
        )
        futures.add(future)
        spawned += 1
    return spawned


def _reannounce(
    torrent: Torrent,
    info_hash: bytes,
    peer_id: bytes,
    manager: PieceManager,
) -> AnnounceResult:
    return announce(
        torrent.announce,
        info_hash,
        peer_id,
        port=6881,
        left=manager.bytes_left(),
        uploaded=0,
        downloaded=manager.downloaded_bytes(),
        event=None,
    )


def download(torrent_path: str, output_path: str) -> None:
    torrent = load_torrent(torrent_path)
    info_hash = torrent.info_hash
    peer_id = generate_peer_id()
    manager = PieceManager(torrent, output_path)

    if manager.is_complete:
        print(f"Download already complete: {output_path}")
        return

    initial = announce(
        torrent.announce,
        info_hash,
        peer_id,
        port=6881,
        left=manager.bytes_left(),
        uploaded=0,
        downloaded=manager.downloaded_bytes(),
        event="started",
    )

    if not initial.peers:
        raise RuntimeError("Tracker returned no peers.")

    destination = "directory" if torrent.is_multi_file else "file"
    print(f"Starting download: {torrent.name}")
    print(f"Output {destination}: {output_path}")
    print(f"Tracker returned {len(initial.peers)} peer(s). Spawning concurrent workers...")

    peer_pool = PeerPool()
    announce_interval = initial.interval
    last_announce = time.monotonic()
    futures: set[Future[None]] = set()

    with ThreadPoolExecutor(max_workers=50) as executor:
        spawned = _spawn_peer_workers(
            executor,
            initial.peers,
            torrent,
            info_hash,
            peer_id,
            manager,
            peer_pool,
            futures,
        )
        print(f"Started {spawned} peer worker(s).")

        while not manager.is_complete:
            time.sleep(0.5)
            futures = {future for future in futures if not future.done()}

            active = peer_pool.active_count()
            elapsed = time.monotonic() - last_announce
            peer_pool_low = active < MIN_ACTIVE_PEERS
            interval_elapsed = elapsed >= announce_interval
            cooldown_elapsed = elapsed >= REANNOUNCE_COOLDOWN_SECONDS

            should_reannounce = interval_elapsed or (peer_pool_low and cooldown_elapsed)
            if not should_reannounce:
                continue

            if peer_pool_low:
                print(
                    f"Active peers dropped to {active}. "
                    "Re-announcing to tracker to replenish peer pool..."
                )
            else:
                print("Announce interval elapsed. Re-announcing to tracker...")

            try:
                result = _reannounce(torrent, info_hash, peer_id, manager)
                announce_interval = result.interval
                last_announce = time.monotonic()
                peer_pool.prepare_reannounce()
                spawned = _spawn_peer_workers(
                    executor,
                    result.peers,
                    torrent,
                    info_hash,
                    peer_id,
                    manager,
                    peer_pool,
                    futures,
                )
                if spawned:
                    print(f"Replenished peer pool with {spawned} new worker(s).")
            except RuntimeError as exc:
                print(f"Re-announce failed: {exc}")

        for future in futures:
            future.result()

    if not manager.is_complete:
        raise RuntimeError("Failed to download all pieces from available peers.")

    print(f"Download complete: {output_path}")
