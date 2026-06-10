import hashlib
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from pieces.torrent import Torrent

BLOCK_SIZE = 2**14


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: Path
    offset: int
    length: int


class PieceManager:
    def __init__(self, torrent: Torrent, output_path: str) -> None:
        self.torrent = torrent
        self.output_path = Path(output_path)
        self.have: set[int] = set()
        self.pending_blocks: dict[int, dict[int, bytes]] = {}
        self.requested: dict[int, set[int]] = {}
        self._lock = threading.Lock()
        self._file_entries = self._build_file_layout()
        self._allocate_storage()
        self._scan_existing_pieces()

    def _build_file_layout(self) -> list[FileEntry]:
        if not self.torrent.is_multi_file:
            return [
                FileEntry(
                    path=self.output_path,
                    offset=0,
                    length=self.torrent.total_length,
                )
            ]

        info = self.torrent.meta_info[b"info"]
        files = info[b"files"]
        entries: list[FileEntry] = []
        global_offset = 0

        for file_item in files:
            path_parts = [
                part.decode("utf-8", errors="replace") for part in file_item[b"path"]
            ]
            file_path = self.output_path.joinpath(*path_parts)
            length = file_item[b"length"]
            entries.append(
                FileEntry(path=file_path, offset=global_offset, length=length)
            )
            global_offset += length

        return entries

    def _allocate_storage(self) -> None:
        if not self.torrent.is_multi_file:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            if self.output_path.exists():
                with open(self.output_path, "r+b") as file:
                    file.seek(0, os.SEEK_END)
                    if file.tell() < self.torrent.total_length:
                        file.truncate(self.torrent.total_length)
            else:
                with open(self.output_path, "wb") as file:
                    file.truncate(self.torrent.total_length)
            return

        os.makedirs(self.output_path, exist_ok=True)
        for entry in self._file_entries:
            entry.path.parent.mkdir(parents=True, exist_ok=True)
            if entry.path.exists():
                with open(entry.path, "r+b") as file:
                    file.seek(0, os.SEEK_END)
                    if file.tell() < entry.length:
                        file.truncate(entry.length)
            else:
                with open(entry.path, "wb") as file:
                    file.truncate(entry.length)

    def _scan_existing_pieces(self) -> None:
        verified = 0
        with self._lock:
            for piece_index in range(self.torrent.num_pieces):
                piece_size = self.piece_size(piece_index)
                global_offset = piece_index * self.torrent.piece_length
                piece_data = self._read_from_storage(global_offset, piece_size)
                expected_hash = self.torrent.piece_hashes[piece_index]
                if hashlib.sha1(piece_data).digest() == expected_hash:
                    self.have.add(piece_index)
                    verified += 1

        total = self.torrent.num_pieces
        if verified > 0:
            percent = (verified / total) * 100 if total else 0.0
            print(
                f"Found {verified}/{total} verified pieces on disk. "
                f"Resuming download from {percent:.1f}%..."
            )

    @property
    def is_complete(self) -> bool:
        with self._lock:
            return len(self.have) == self.torrent.num_pieces

    def completed_piece_count(self) -> int:
        with self._lock:
            return len(self.have)

    def downloaded_bytes(self) -> int:
        with self._lock:
            return sum(self.piece_size(index) for index in self.have)

    def bytes_left(self) -> int:
        return self.torrent.total_length - self.downloaded_bytes()

    def piece_size(self, piece_index: int) -> int:
        if piece_index < 0 or piece_index >= self.torrent.num_pieces:
            raise ValueError(f"Invalid piece index: {piece_index}")

        if piece_index == self.torrent.num_pieces - 1:
            return self.torrent.total_length - piece_index * self.torrent.piece_length
        return self.torrent.piece_length

    def block_length(self, piece_index: int, begin: int) -> int:
        remaining = self.piece_size(piece_index) - begin
        if remaining <= 0:
            raise ValueError(
                f"Block offset {begin} is beyond piece {piece_index} boundary."
            )
        return min(BLOCK_SIZE, remaining)

    def block_offsets(self, piece_index: int) -> list[int]:
        offsets: list[int] = []
        begin = 0
        piece_size = self.piece_size(piece_index)
        while begin < piece_size:
            offsets.append(begin)
            begin += self.block_length(piece_index, begin)
        return offsets

    def next_request(self) -> tuple[int, int, int] | None:
        with self._lock:
            for piece_index in range(self.torrent.num_pieces):
                if piece_index in self.have:
                    continue

                for begin in self.block_offsets(piece_index):
                    if begin in self.pending_blocks.get(piece_index, {}):
                        continue
                    if begin in self.requested.get(piece_index, set()):
                        continue

                    self.requested.setdefault(piece_index, set()).add(begin)
                    return piece_index, begin, self.block_length(piece_index, begin)

            return None

    def mark_requested(self, piece_index: int, begin: int) -> None:
        with self._lock:
            self.requested.setdefault(piece_index, set()).add(begin)

    def handle_block(self, piece_index: int, begin: int, block_data: bytes) -> bool:
        with self._lock:
            if piece_index in self.have:
                return False

            expected_length = self.block_length(piece_index, begin)
            if len(block_data) != expected_length:
                raise ValueError(
                    f"Unexpected block size for piece {piece_index} at offset {begin}."
                )

            piece_blocks = self.pending_blocks.setdefault(piece_index, {})
            piece_blocks[begin] = block_data
            self.requested.get(piece_index, set()).discard(begin)

            if not self._all_blocks_received(piece_index):
                return False

            piece_data = b"".join(
                piece_blocks[offset] for offset in sorted(piece_blocks.keys())
            )
            expected_hash = self.torrent.piece_hashes[piece_index]
            if hashlib.sha1(piece_data).digest() != expected_hash:
                del self.pending_blocks[piece_index]
                self.requested.pop(piece_index, None)
                return False

            global_offset = piece_index * self.torrent.piece_length
            self._write_to_storage(global_offset, piece_data)

            self.have.add(piece_index)
            del self.pending_blocks[piece_index]
            self.requested.pop(piece_index, None)
            return True

    def _read_from_storage(self, global_offset: int, length: int) -> bytes:
        buffer = bytearray()
        remaining = length
        cursor = global_offset

        while remaining > 0:
            entry = self._entry_for_offset(cursor)
            if entry is None:
                raise ValueError(f"Global offset {cursor} is outside torrent data.")

            local_offset = cursor - entry.offset
            readable = min(remaining, entry.length - local_offset)

            with open(entry.path, "rb") as file:
                file.seek(local_offset)
                chunk = file.read(readable)
                if len(chunk) != readable:
                    raise ValueError(
                        f"Expected {readable} bytes at offset {cursor}, got {len(chunk)}."
                    )
                buffer.extend(chunk)

            remaining -= readable
            cursor += readable

        return bytes(buffer)

    def _write_to_storage(self, global_offset: int, data: bytes) -> None:
        remaining = data
        cursor = global_offset

        while remaining:
            entry = self._entry_for_offset(cursor)
            if entry is None:
                raise ValueError(f"Global offset {cursor} is outside torrent data.")

            local_offset = cursor - entry.offset
            writable = min(len(remaining), entry.length - local_offset)

            with open(entry.path, "r+b") as file:
                file.seek(local_offset)
                file.write(remaining[:writable])

            remaining = remaining[writable:]
            cursor += writable

    def _entry_for_offset(self, global_offset: int) -> FileEntry | None:
        for entry in self._file_entries:
            if entry.offset <= global_offset < entry.offset + entry.length:
                return entry
        return None

    def _all_blocks_received(self, piece_index: int) -> bool:
        piece_blocks = self.pending_blocks.get(piece_index)
        if not piece_blocks:
            return False
        return all(
            offset in piece_blocks for offset in self.block_offsets(piece_index)
        )
