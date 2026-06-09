import hashlib

from pieces.bencoding import Decoder, encode
from pieces.torrent import Torrent

# SHA-1 of the canonical bencode for the ``info`` fixture below.
KNOWN_INFO_HASH_HEX = "742c7591f2b49330e05e90550710c945a5af2c3d"


def _roundtrip(obj: int | str | bytes | list | dict) -> None:
    encoded = encode(obj)
    decoded = Decoder(encoded).decode()
    expected = obj.encode("utf-8") if isinstance(obj, str) else obj
    assert decoded == expected
    assert encode(decoded) == encoded


def test_bencoding_roundtrip() -> None:
    _roundtrip(42)
    _roundtrip(-7)
    _roundtrip(b"spam")
    _roundtrip("eggs")
    _roundtrip([b"alpha", 1, b"beta"])
    _roundtrip(
        {
            b"cow": b"moo",
            b"spam": [b"nested", 99],
            b"count": 3,
        }
    )


def test_dict_keys_encoded_in_lexicographical_order() -> None:
    scrambled = {b"z": 1, b"a": 2, b"m": 3}
    expected = b"d1:ai2e1:mi3e1:zi1ee"

    assert encode(scrambled) == expected

    scrambled_str_keys = {"z": 1, "a": 2, "m": 3}
    assert encode(scrambled_str_keys) == expected


def test_info_hash_matches_known_sha1() -> None:
    info = {
        b"length": 100,
        b"name": b"test.txt",
        b"piece length": 16384,
        b"pieces": bytes.fromhex("aa" * 20),
    }
    meta_info = {
        b"announce": b"http://tracker.example.com/announce",
        b"info": info,
    }

    torrent = Torrent(meta_info)

    assert torrent.info_hash == bytes.fromhex(KNOWN_INFO_HASH_HEX)
    assert torrent.info_hash == hashlib.sha1(encode(info)).digest()
    assert len(torrent.info_hash) == 20


def test_piece_hashes_and_num_pieces() -> None:
    piece_a = b"\x01" * 20
    piece_b = b"\x02" * 20
    meta_info = {
        b"announce": b"http://tracker.example.com/announce",
        b"info": {
            b"name": b"test.txt",
            b"piece length": 16384,
            b"length": 32768,
            b"pieces": piece_a + piece_b,
        },
    }

    torrent = Torrent(meta_info)

    assert torrent.num_pieces == 2
    assert torrent.piece_hashes == [piece_a, piece_b]
