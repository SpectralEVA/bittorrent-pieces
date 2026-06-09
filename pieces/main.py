import argparse
import sys
from pathlib import Path

from pieces.client import download, load_torrent


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Minimal BitTorrent client for single-file and multi-file torrents."
    )
    parser.add_argument(
        "torrent",
        help="Path to the .torrent file",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file or directory path (defaults to the torrent name)",
    )
    args = parser.parse_args()

    torrent_path = Path(args.torrent)
    if not torrent_path.is_file():
        print(f"Error: torrent file not found: {torrent_path}", file=sys.stderr)
        sys.exit(1)

    output_path = args.output
    if output_path is None:
        torrent = load_torrent(str(torrent_path))
        output_path = torrent.name

    try:
        download(str(torrent_path), output_path)
    except Exception as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
