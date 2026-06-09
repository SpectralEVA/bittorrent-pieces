def encode(obj: int | str | bytes | list | dict) -> bytes:
    """
    Recursively encode a Python object into canonical bencode bytes.

    Dictionary keys are sorted lexicographically by their raw byte value
    before encoding, as required by BEP 3 for info-hash computation.
    """
    if isinstance(obj, bool):
        raise TypeError("Booleans are not valid bencode integers.")
    if isinstance(obj, int):
        return b"i" + str(obj).encode("ascii") + b"e"
    if isinstance(obj, str):
        return encode(obj.encode("utf-8"))
    if isinstance(obj, bytes):
        return str(len(obj)).encode("ascii") + b":" + obj
    if isinstance(obj, list):
        return b"l" + b"".join(encode(item) for item in obj) + b"e"
    if isinstance(obj, dict):
        normalized: dict[bytes, int | str | bytes | list | dict] = {}
        for key, value in obj.items():
            if isinstance(key, str):
                key = key.encode("utf-8")
            elif not isinstance(key, bytes):
                raise TypeError(
                    f"Dictionary keys must be str or bytes, got {type(key).__name__}"
                )
            normalized[key] = value

        parts = [b"d"]
        for key in sorted(normalized.keys()):
            parts.append(encode(key))
            parts.append(encode(normalized[key]))
        parts.append(b"e")
        return b"".join(parts)

    raise TypeError(f"Unsupported type for bencoding: {type(obj).__name__}")


class Decoder:
    """
    A modern Python 3.11+ Bencoding decoder.
    Decodes standard integers, byte-strings, lists, and dictionaries.
    """
    def __init__(self, data: bytes):
        if not isinstance(data, bytes):
            raise TypeError("Bencoded data must be raw bytes.")
        self.data = data
        self.index = 0

    def decode(self):
        if self.index >= len(self.data):
            return None
            
        token = self.data[self.index:self.index+1]
        
        if token == b'i':
            return self._decode_int()
        elif token == b'l':
            return self._decode_list()
        elif token == b'd':
            return self._decode_dict()
        elif token.isdigit():
            return self._decode_string()
        else:
            raise ValueError(f"Invalid bencoding token '{token}' at index {self.index}")

    def _decode_int(self) -> int:
        # Example format: i42e
        self.index += 1  # Move past 'i'
        end = self.data.find(b'e', self.index)
        if end == -1:
            raise ValueError("Unterminated integer token")
        
        val = int(self.data[self.index:end])
        self.index = end + 1  # Move past 'e'
        return val

    def _decode_string(self) -> bytes:
        # Example format: 4:spam
        colon = self.data.find(b':', self.index)
        if colon == -1:
            raise ValueError("Invalid string token: missing colon")
        length = int(self.data[self.index:colon])
        
        start = colon + 1
        end = start + length
        
        val = self.data[start:end]
        self.index = end
        return val

    def _decode_list(self) -> list:
        # Example format: l4:spami42ee -> [b'spam', 42]
        self.index += 1  # Move past 'l'
        res = []
        
        while self.data[self.index:self.index+1] != b'e':
            res.append(self.decode())
            
        self.index += 1  # Move past 'e'
        return res

    def _decode_dict(self) -> dict:
        # Example format: d3:cow3:moo4:spamli123eee -> {b'cow': b'moo', b'spam': [123]}
        self.index += 1  # Move past 'd'
        res = {}
        
        while self.data[self.index:self.index+1] != b'e':
            # In bencoding, keys are ALWAYS bencoded strings
            key = self._decode_string()
            # Values can be any valid bencoded type
            value = self.decode()
            res[key] = value
            
        self.index += 1  # Move past 'e'
        return res