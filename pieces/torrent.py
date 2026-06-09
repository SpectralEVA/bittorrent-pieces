import hashlib

from pieces.bencoding import encode


class Torrent:
    def __init__(self, meta_info: dict[bytes, object]):
        """
        Wraps bdecoded torrent metadata into a clean, queryable object.
        Handles both Single-File and Multi-File structures automatically.
        """
        self.meta_info = meta_info
        
        # 1. Logistics: Extract tracker coordinator URL
        # We decode the bytes into a clean text string for easy use later
        self.announce = meta_info[b'announce'].decode('utf-8', errors='replace')
        
        # 2. Payload: Step into the inner 'info' bucket
        info = self.meta_info[b'info']
        
        self.name = info[b'name'].decode('utf-8', errors='replace')
        self.piece_length = info[b'piece length']
        
        # Keep pieces as raw binary bytes because it is a long sequence 
        # of concatenated 20-byte SHA-1 fingerprints
        self.pieces = info[b'pieces']
        
        # 3. Size Calculation: Single-File Mode vs Multi-File Mode
        if b'length' in info:
            # Single-file mode: Total size is explicitly listed right here
            self.total_length = info[b'length']
            self.is_multi_file = False
        elif b'files' in info:
            # Multi-file mode: Loop through the files list and sum up all lengths
            self.total_length = sum(file_item[b'length'] for file_item in info[b'files'])
            self.is_multi_file = True
        else:
            raise ValueError("Malformed torrent file: metadata contains neither length nor files.")

    @property
    def info_hash(self) -> bytes:
        """20-byte SHA-1 digest of the canonical bencoded ``info`` dictionary."""
        return hashlib.sha1(encode(self.meta_info[b"info"])).digest()

    @property
    def piece_hashes(self) -> list[bytes]:
        """Individual 20-byte SHA-1 piece hashes extracted from ``pieces``."""
        return [self.pieces[i : i + 20] for i in range(0, len(self.pieces), 20)]

    @property
    def num_pieces(self) -> int:
        """Total number of piece hashes in this torrent."""
        return len(self.pieces) // 20

    def __str__(self) -> str:
        """A simple printer format so you can see object details easily"""
        return (
            f"Torrent Name: {self.name}\n"
            f"Tracker URL:  {self.announce}\n"
            f"Total Size:   {self.total_length} bytes\n"
            f"Piece Size:   {self.piece_length} bytes\n"
            f"Total Pieces: {self.num_pieces}"
        )