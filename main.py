from pieces.bencoding import Decoder
from pieces.torrent import Torrent

def main():
    print("--- BitTorrent Client: Metadata Test ---")
    
    # This is a raw bencoded dictionary representing a fake torrent file.
    raw_torrent_data = (
        b"d8:announce27:http://tracker.example.com/4:infod"
        b"4:name9:movie.mp412:piece lengthi16384e6:lengthi5242880e"
        b"6:pieces20:12345678901234567890ee"
    )
    
    try:
        # 1. Feed the raw bytes into your Decoder machine (from bencoding.py)
        print("[1] Initializing decoder...")
        decoder = Decoder(raw_torrent_data)
        decoded_dict = decoder.decode()
        
        # 2. Feed the decoded dictionary into your Torrent wrapper
        print("[2] Parsing metadata into Torrent object...")
        torrent = Torrent(decoded_dict)
        
        # 3. Print the results using the __str__ formatter
        print("\n--- Parsed Torrent Stats ---")
        print(torrent)
        print("----------------------------")
        
    except Exception as e:
        print(f"\n[ERROR] Something went wrong: {e}")

if __name__ == "__main__":
    main()
