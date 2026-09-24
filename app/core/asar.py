"""Minimal pure-Python reader/writer for Electron asar archives.

Only what the patcher needs: read files out of an archive and write a copy of
it with some files replaced. Unpacked entries (in app.asar.unpacked/) and
symlinks are carried over untouched, so no extract/repack round-trip is needed
and Node.js is not required.

Layout: [uint32 4][uint32 header_pickle_size] then a Chromium pickle holding
[uint32 payload_size][int32 json_len][json][pad to 4], then file data. Each
file entry's "offset" is relative to the end of the header.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
from typing import Iterator

_BLOCK_SIZE = 4 * 1024 * 1024


class AsarArchive:
    def __init__(self, path: str) -> None:
        self.path = path
        with open(path, "rb") as fh:
            size_pickle = fh.read(8)
            _, header_size = struct.unpack("<II", size_pickle)
            header_pickle = fh.read(header_size)
        _payload, json_len = struct.unpack("<Ii", header_pickle[:8])
        self.header = json.loads(header_pickle[8:8 + json_len].decode("utf-8"))
        self.data_offset = 8 + header_size

    # ---- reading ---- #

    def files(self) -> Iterator[tuple[str, dict]]:
        """(path, entry) for every file/link, in archive order. Paths use '/'."""

        def walk(node: dict, prefix: str):
            for name, entry in node["files"].items():
                path = f"{prefix}{name}"
                if "files" in entry:
                    yield from walk(entry, path + "/")
                else:
                    yield path, entry

        yield from walk(self.header, "")

    def entry(self, path: str) -> dict | None:
        node = self.header
        for part in path.strip("/").split("/"):
            node = node.get("files", {}).get(part)
            if node is None:
                return None
        return node

    def read(self, path: str) -> bytes:
        e = self.entry(path)
        if e is None or "files" in e or "link" in e:
            raise FileNotFoundError(path)
        if e.get("unpacked"):
            raise ValueError(f"{path} is stored in app.asar.unpacked")
        with open(self.path, "rb") as fh:
            fh.seek(self.data_offset + int(e["offset"]))
            return fh.read(int(e["size"]))

    # ---- writing ---- #

    def write_patched(self, out_path: str, replacements: dict[str, bytes]) -> None:
        """Write a copy of the archive to out_path with `replacements`
        ({path: new_bytes}) swapped in.

        The original data section is copied byte-for-byte (entries may share
        data and are not stored in header order, so it is not rebuilt); each
        replacement is appended after it and only its entry is repointed.
        """
        header = json.loads(json.dumps(self.header))  # deep copy
        with open(self.path, "rb") as fh:
            fh.seek(0, 2)
            data_len = fh.tell() - self.data_offset

        offset = data_len
        for path, data in replacements.items():
            node = header
            for part in path.strip("/").split("/"):
                node = node.get("files", {}).get(part)
                if node is None:
                    raise FileNotFoundError(path)
            if "files" in node or "link" in node or node.get("unpacked"):
                raise ValueError(f"{path} is not a packed file")
            node["size"] = len(data)
            node["offset"] = str(offset)
            if "integrity" in node:
                node["integrity"] = _integrity(data)
            offset += len(data)

        blob = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        pad = (4 - len(blob) % 4) % 4
        payload = struct.pack("<i", len(blob)) + blob + b"\0" * pad
        header_pickle = struct.pack("<I", len(payload)) + payload

        with open(self.path, "rb") as src, open(out_path, "wb") as dst:
            dst.write(struct.pack("<II", 4, len(header_pickle)))
            dst.write(header_pickle)
            src.seek(self.data_offset)
            _copy_exact(src, dst, data_len)
            for data in replacements.values():
                dst.write(data)


def _integrity(data: bytes) -> dict:
    return {
        "algorithm": "SHA256",
        "hash": hashlib.sha256(data).hexdigest(),
        "blockSize": _BLOCK_SIZE,
        "blocks": [
            hashlib.sha256(data[i:i + _BLOCK_SIZE]).hexdigest()
            for i in range(0, max(len(data), 1), _BLOCK_SIZE)
        ],
    }


def _copy_exact(src, dst, n: int) -> None:
    while n > 0:
        chunk = src.read(min(n, 1024 * 1024))
        if not chunk:
            raise EOFError("asar archive is truncated")
        dst.write(chunk)
        n -= len(chunk)


# ---- Electron fuses ---- #

_FUSE_SENTINEL = b"dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX"
# Index into the fuse wire (Electron's FuseV1Options).
FUSE_ASAR_INTEGRITY = 4


def set_fuse(exe_path: str, index: int, enabled: bool) -> bool:
    """Flip one Electron fuse in place. Returns False if the exe has no fuse
    wire or does not carry that fuse (nothing to do)."""
    with open(exe_path, "rb") as fh:
        data = bytearray(fh.read())
    at = data.find(_FUSE_SENTINEL)
    if at < 0 or data.find(_FUSE_SENTINEL, at + 1) >= 0:
        return False
    # sentinel, then [version byte][fuse count][one '0'/'1'/'r' byte per fuse]
    count = data[at + len(_FUSE_SENTINEL) + 1]
    pos = at + len(_FUSE_SENTINEL) + 2 + index
    if index >= count or data[pos] not in (ord("0"), ord("1")):
        return False
    data[pos] = ord("1") if enabled else ord("0")
    tmp = exe_path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    shutil.move(tmp, exe_path)
    return True
