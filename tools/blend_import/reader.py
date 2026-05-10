"""Block walk + pointer resolution + typed field reads for .blend files.

Format reference: https://wiki.blender.org/wiki/Source/File_Format

The "every pointer is the original in-memory address; every block records its
own old address; resolve by lookup" trick is described in the canonical wiki
spec and the atmind walkthrough. The Blender C reference for the same idea
lives in `source/blender/blenkernel/intern/readfile.c` (GPL-2.0-or-later, read
for understanding only — not mirrored).
"""

from __future__ import annotations

import gzip
import io
import struct as _struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .sdna import FieldDecl, FileHeader, SDNA, StructDecl, decode_header, decode_sdna


# ---------------------------------------------------------------------------
# Decompression. Blender 3.0+ wraps the file in zstd (magic 0x28 B5 2F FD);
# pre-3.0 used gzip (magic 0x1F 0x8B); otherwise raw.

_ZSTD_MAGIC = b"\x28\xB5\x2F\xFD"
_GZIP_MAGIC = b"\x1F\x8B"


def _decompress(data: bytes) -> bytes:
    if data.startswith(_ZSTD_MAGIC):
        try:
            import zstandard  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "zstandard is required to read Blender 3.0+ .blend files; "
                "install with `pip install zstandard`"
            ) from exc
        return zstandard.ZstdDecompressor().decompress(data)
    if data.startswith(_GZIP_MAGIC):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as fh:
            return fh.read()
    return data


# ---------------------------------------------------------------------------
# Block header. Two on-disk variants, picked by the file header.
#
# Legacy ("BHead8", legacy 12-byte file header):
#   char[4] code, uint32 size, ptr old, uint32 sdna_index, uint32 count
#   Header size = 16 + pointer_size = 24 bytes for 8-byte pointers.
#
# Extended ("BLargeHead", 17-byte file header — Blender 4.0+ for blocks >2 GiB):
#   char[4] code, uint32 sdna_index, uint64 old, uint64 size, uint32 count,
#   uint32 _pad
#   Header size = 32 bytes. Both `old` and `size` widen to 64 bits; the
#   trailing 4-byte pad keeps the next block 8-byte aligned. Verified
#   empirically against a Blender 5.1-authored fixture (SC block has
#   sdna_index=757 = Scene struct, count=1; TEST thumbnail at offset 313 with
#   size=65544 lands the next block at GLOB@65889 exactly).

@dataclass(frozen=True)
class Block:
    code: str
    size: int
    old: int
    sdna_index: int
    count: int
    payload_offset: int  # absolute offset into the decompressed buffer

    def payload(self, buf: bytes) -> memoryview:
        return memoryview(buf)[self.payload_offset:self.payload_offset + self.size]


def _block_header_fmt(header: FileHeader) -> tuple[str, int, bool]:
    """Return (struct_fmt, header_size_bytes, is_extended)."""
    if header.header_size == 17:
        # Extended (BLargeHead) layout — 32 bytes regardless of ptr size:
        # code(4) + sdna_index(u32) + old(u64) + size(u64) + count(u32) + _pad(u32)
        fmt = header.endian_char + "4sI" + "Q" + "Q" + "II"
    else:
        # Legacy (BHead) layout.
        fmt = header.endian_char + "4sI" + header.ptr_fmt + "II"
    return fmt, _struct.calcsize(fmt), header.header_size == 17


# ---------------------------------------------------------------------------
# BlendFile — parse-once, query-many.

class BlendFile:
    """Parsed .blend file: SDNA + block table + pointer dictionary."""

    def __init__(self, raw: bytes):
        self.buf: bytes = _decompress(raw)
        self.header: FileHeader = decode_header(self.buf[:17])
        self.blocks: list[Block] = []
        self.by_old: dict[int, Block] = {}
        self.by_code: dict[str, list[Block]] = {}
        self._scan_blocks()
        # Locate DNA1 and decode SDNA.
        dna_blocks = self.by_code.get("DNA1", [])
        if not dna_blocks:
            raise ValueError("file has no DNA1 block — not a valid .blend")
        dna = dna_blocks[0]
        self.sdna: SDNA = decode_sdna(bytes(dna.payload(self.buf)), self.header)

    # -- block-walk pass -----------------------------------------------------

    def _scan_blocks(self) -> None:
        fmt, hsize, is_ext = _block_header_fmt(self.header)
        pos = self.header.header_size
        end = len(self.buf)
        while pos + hsize <= end:
            if is_ext:
                code, sdna_idx, old, size, count, _pad = _struct.unpack_from(fmt, self.buf, pos)
            else:
                code, size, old, sdna_idx, count = _struct.unpack_from(fmt, self.buf, pos)
            code_s = code.rstrip(b"\x00").decode("ascii", errors="replace")
            block = Block(
                code=code_s, size=size, old=old,
                sdna_index=sdna_idx, count=count,
                payload_offset=pos + hsize,
            )
            self.blocks.append(block)
            if old != 0:
                self.by_old[old] = block
            self.by_code.setdefault(code_s, []).append(block)
            pos = block.payload_offset + size
            if code_s == "ENDB":
                break
        else:
            # Reached EOF without ENDB; permissive — fall through.
            pass

    # -- typed reads ---------------------------------------------------------

    @classmethod
    def from_path(cls, path: str | Path) -> "BlendFile":
        return cls(Path(path).read_bytes())

    def struct_of(self, block: Block) -> StructDecl:
        return self.sdna.structs[block.sdna_index]

    def follow(self, ptr: int) -> Block | None:
        return self.by_old.get(ptr)

    def field_bytes(self, block: Block, struct: StructDecl, name: str,
                    *, instance_index: int = 0) -> memoryview:
        fd = struct.by_name.get(name)
        if fd is None:
            raise KeyError(f"struct {struct.type_name} has no field {name!r}")
        base = block.payload_offset + instance_index * struct.size + fd.offset
        return memoryview(self.buf)[base:base + fd.size]

    def read_int(self, block: Block, struct: StructDecl, name: str,
                 *, instance_index: int = 0) -> int:
        fd = struct.by_name[name]
        raw = self.field_bytes(block, struct, name, instance_index=instance_index)
        endian = self.header.endian_char
        if fd.is_pointer:
            (val,) = _struct.unpack(endian + self.header.ptr_fmt, raw[:self.header.pointer_size])
            return val
        sized = {1: "b", 2: "h", 4: "i", 8: "q"}.get(fd.type_size)
        if sized is None:
            raise ValueError(f"unsupported int field size: {fd.type_size}")
        # Default to signed for char/short/int/long — caller can re-interpret if needed.
        if fd.type_name in ("char", "uchar", "uint8_t", "ushort", "uint", "uint32_t",
                            "uint64_t", "ulong"):
            sized = sized.upper()
        (val,) = _struct.unpack(endian + sized, raw[:fd.type_size])
        return val

    def read_float(self, block: Block, struct: StructDecl, name: str,
                   *, instance_index: int = 0, count: int = 1) -> list[float]:
        fd = struct.by_name[name]
        raw = self.field_bytes(block, struct, name, instance_index=instance_index)
        endian = self.header.endian_char
        n = min(count if count > 0 else fd.array_len, fd.array_len)
        return list(_struct.unpack(endian + "f" * n, raw[:4 * n]))

    def read_pointer(self, block: Block, struct: StructDecl, name: str,
                     *, instance_index: int = 0) -> int:
        return self.read_int(block, struct, name, instance_index=instance_index)

    def read_string(self, block: Block, struct: StructDecl, name: str,
                    *, instance_index: int = 0) -> str:
        raw = bytes(self.field_bytes(block, struct, name, instance_index=instance_index))
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")

    def read_array(self, block: Block, struct: StructDecl, name: str,
                   *, instance_index: int = 0) -> bytes:
        return bytes(self.field_bytes(block, struct, name, instance_index=instance_index))

    def iter_instances(self, block: Block) -> Iterator[int]:
        return iter(range(block.count or 1))

    # -- listbase walk -------------------------------------------------------
    # Blender's ListBase {first, last} pointers thread datablocks together via
    # an embedded "Link {next, prev}" head on each entry. For a linked block
    # at pointer P referenced by the listbase, follow P to a Block, then read
    # the *next pointer at offset 0 of the block's struct (the embedded Link
    # is always the first field on listed datablocks).
    def walk_listbase(self, first_ptr: int) -> Iterator[Block]:
        ptr = first_ptr
        seen: set[int] = set()
        while ptr and ptr not in seen:
            seen.add(ptr)
            blk = self.by_old.get(ptr)
            if blk is None:
                return
            yield blk
            # The first field of any listbase-linked datablock is `*next`.
            # Read raw pointer from the start of the payload.
            ptr_size = self.header.pointer_size
            fmt = self.header.endian_char + self.header.ptr_fmt
            (ptr,) = _struct.unpack_from(fmt, self.buf, blk.payload_offset)


__all__ = ["BlendFile", "Block"]
