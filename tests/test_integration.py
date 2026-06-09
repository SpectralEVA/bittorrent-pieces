import hashlib
import threading
from pathlib import Path

from pieces.pieces_manager import BLOCK_SIZE, PieceManager
from pieces.torrent import Torrent


def _build_torrent(
    piece_length: int,
    piece_data_list: list[bytes],
    total_length: int | None = None,
) -> Torrent:
    pieces = b"".join(hashlib.sha1(data).digest() for data in piece_data_list)
    if total_length is None:
        total_length = sum(len(data) for data in piece_data_list)

    meta_info = {
        b"announce": b"http://tracker.example.com/announce",
        b"info": {
            b"name": b"integration.bin",
            b"piece length": piece_length,
            b"length": total_length,
            b"pieces": pieces,
        },
    }
    return Torrent(meta_info)


def _build_multi_file_torrent(
    piece_length: int,
    files: list[tuple[list[bytes], int]],
    piece_data_list: list[bytes],
) -> Torrent:
    pieces = b"".join(hashlib.sha1(data).digest() for data in piece_data_list)
    total_length = sum(length for _, length in files)

    meta_info = {
        b"announce": b"http://tracker.example.com/announce",
        b"info": {
            b"name": b"multi-root",
            b"piece length": piece_length,
            b"files": [
                {b"path": path_parts, b"length": length}
                for path_parts, length in files
            ],
            b"pieces": pieces,
        },
    }
    return Torrent(meta_info)


def test_piece_manager_concatenates_verifies_and_writes(tmp_path: Path) -> None:
    piece_one = b"A" * BLOCK_SIZE
    piece_two = b"B" * (BLOCK_SIZE // 2)
    torrent = _build_torrent(piece_length=BLOCK_SIZE, piece_data_list=[piece_one, piece_two])

    output_file = tmp_path / "integration.bin"
    manager = PieceManager(torrent, str(output_file))

    assert output_file.stat().st_size == torrent.total_length

    assert manager.handle_block(0, 0, piece_one) is True
    assert manager.have == {0}
    assert manager.handle_block(0, 0, piece_one) is False

    assert manager.handle_block(1, 0, piece_two) is True
    assert manager.have == {0, 1}
    assert manager.is_complete

    written = output_file.read_bytes()
    assert written == piece_one + piece_two + b"\x00" * (torrent.total_length - len(piece_one) - len(piece_two))


def test_piece_manager_rejects_invalid_hash_and_retries(tmp_path: Path) -> None:
    valid_piece = b"verified-data"
    torrent = _build_torrent(
        piece_length=BLOCK_SIZE,
        piece_data_list=[valid_piece],
        total_length=len(valid_piece),
    )

    output_file = tmp_path / "retry.bin"
    manager = PieceManager(torrent, str(output_file))

    bad_piece = b"X" * len(valid_piece)
    assert manager.handle_block(0, 0, bad_piece) is False
    assert 0 not in manager.have
    assert 0 not in manager.pending_blocks

    assert manager.handle_block(0, 0, valid_piece) is True
    assert output_file.read_bytes()[: len(valid_piece)] == valid_piece


def test_piece_manager_block_length_for_final_piece_block(tmp_path: Path) -> None:
    final_piece_size = 1000
    torrent = _build_torrent(
        piece_length=BLOCK_SIZE,
        piece_data_list=[b"X" * final_piece_size],
        total_length=final_piece_size,
    )
    manager = PieceManager(torrent, str(tmp_path / "partial.bin"))

    assert manager.block_length(0, 0) == final_piece_size
    assert manager.block_offsets(0) == [0]


def test_write_to_storage_spans_file_boundary(tmp_path: Path) -> None:
    file_one_size = 100
    file_two_size = 100
    span_data = b"X" * 100
    torrent = _build_multi_file_torrent(
        piece_length=BLOCK_SIZE,
        files=[
            ([b"file1.txt"], file_one_size),
            ([b"file2.txt"], file_two_size),
        ],
        piece_data_list=[b"Z" * BLOCK_SIZE],
    )

    output_dir = tmp_path / "multi-root"
    manager = PieceManager(torrent, str(output_dir))

    manager._write_to_storage(50, span_data)

    file_one = (output_dir / "file1.txt").read_bytes()
    file_two = (output_dir / "file2.txt").read_bytes()

    assert file_one[:50] == b"\x00" * 50
    assert file_one[50:] == b"X" * 50
    assert file_two[:50] == b"X" * 50
    assert file_two[50:] == b"\x00" * 50


def test_concurrent_handle_block_is_thread_safe(tmp_path: Path) -> None:
    piece_count = 8
    piece_data_list = [bytes([index]) * BLOCK_SIZE for index in range(piece_count)]
    torrent = _build_torrent(
        piece_length=BLOCK_SIZE,
        piece_data_list=piece_data_list,
        total_length=BLOCK_SIZE * piece_count,
    )

    output_file = tmp_path / "concurrent.bin"
    manager = PieceManager(torrent, str(output_file))
    errors: list[Exception] = []

    def worker(piece_index: int) -> None:
        try:
            block = piece_data_list[piece_index]
            assert manager.handle_block(piece_index, 0, block) is True
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(index,))
        for index in range(piece_count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert manager.is_complete
    assert manager.completed_piece_count() == piece_count
    assert output_file.read_bytes() == b"".join(piece_data_list)