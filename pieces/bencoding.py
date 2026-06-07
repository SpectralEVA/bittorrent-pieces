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