import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from pieces.client import PeerPool, _spawn_peer_workers
from pieces.tracker import Peer


def test_peer_pool_filters_connected_and_failed_peers() -> None:
    pool = PeerPool()
    peer_a = Peer(host="10.0.0.1", port=6881)
    peer_b = Peer(host="10.0.0.2", port=6881)
    peer_c = Peer(host="10.0.0.3", port=6881)

    pool.register_connected(peer_a)
    pool.mark_failed(peer_b)

    filtered = pool.filter_new_peers([peer_a, peer_b, peer_c])
    assert filtered == [peer_c]

    pool.prepare_reannounce()
    filtered = pool.filter_new_peers([peer_a, peer_b, peer_c])
    assert filtered == [peer_b, peer_c]


def test_peer_pool_active_count_is_thread_safe() -> None:
    pool = PeerPool()
    peer = Peer(host="127.0.0.1", port=6881)
    errors: list[Exception] = []

    def worker(register: bool) -> None:
        try:
            if register:
                pool.register_connected(peer)
            else:
                pool.unregister_connected(peer)
        except Exception as exc:
            errors.append(exc)

    threads = []
    for _ in range(20):
        threads.append(threading.Thread(target=worker, args=(True,)))
        threads.append(threading.Thread(target=worker, args=(False,)))

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert pool.active_count() == 0


def test_spawn_peer_workers_only_starts_unique_peers() -> None:
    pool = PeerPool()
    peers = [
        Peer(host="192.168.1.1", port=6881),
        Peer(host="192.168.1.2", port=6882),
    ]
    pool.register_connected(peers[0])

    torrent = MagicMock()
    manager = MagicMock()
    manager.is_complete = False
    futures: set = set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        with patch("pieces.client._download_from_peer") as mock_worker:
            spawned = _spawn_peer_workers(
                executor,
                peers,
                torrent,
                b"\xaa" * 20,
                b"\xbb" * 20,
                manager,
                pool,
                futures,
            )
            time.sleep(0.1)

    assert spawned == 1
    assert mock_worker.call_count == 1
    assert mock_worker.call_args[0][0] == peers[1]
