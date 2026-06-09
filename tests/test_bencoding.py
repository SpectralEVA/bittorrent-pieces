from pieces.bencoding import Decoder, encode


def _roundtrip(obj: int | str | bytes | list | dict) -> None:
    encoded = encode(obj)
    decoded = Decoder(encoded).decode()
    expected = obj.encode("utf-8") if isinstance(obj, str) else obj
    assert decoded == expected
    assert encode(decoded) == encoded


def test_bencoding_roundtrip() -> None:
    _roundtrip(0)
    _roundtrip(-1024)
    _roundtrip(b"")
    _roundtrip(b"binary-\x00-data")
    _roundtrip("unicode-text")
    _roundtrip([])
    _roundtrip([b"a", 1, b"b", [2, b"c"]])
    _roundtrip(
        {
            b"zeta": {
                b"nested": [b"list", {b"inner": 7}],
                b"alpha": b"value",
            },
            b"beta": 42,
            b"gamma": [b"one", b"two", 3],
        }
    )
