"""SDNA (Structure DNA) decoder for the .blend file format.

Format reference: https://wiki.blender.org/wiki/Source/File_Format
The DNA1 block fully self-describes every other typed block in the file, so the
parser hard-codes zero C struct layouts. Read for understanding, not mirrored:
Blender's `source/blender/blenkernel/intern/dna_genfile.c` (GPL-2.0-or-later).

This module is pure parsing — it produces SDNA tables and field descriptors;
field-by-name reads from a payload byte buffer live in :mod:`reader`.
"""

from __future__ import annotations

import re
import struct as _struct
from dataclasses import dataclass, field
from typing import Iterable


# Header layouts --------------------------------------------------------------
# Two on-disk variants exist, distinguished by the bytes immediately after the
# "BLENDER" magic.
#
# Legacy 12-byte header (pre-Blender-4.0 file format):
#   0..6  ASCII "BLENDER"
#   7     '_' = 4-byte pointers, '-' = 8-byte pointers
#   8     'v' = little-endian, 'V' = big-endian
#   9..11 ASCII version digits, e.g. "403"
#
# Extended 17-byte header (Blender 4.0+ "version 17" header — adds support for
# files >2 GB and a 4-char version string):
#   0..6   ASCII "BLENDER"
#   7..8   ASCII "17" (header-format magic)
#   9      '_' or '-' (pointer size)
#   10..11 ASCII "01" (file-format sub-version; reserved)
#   12     'v' or 'V' (endianness)
#   13..16 ASCII version, e.g. "0501"
HEADER_MAGIC = b"BLENDER"
LEGACY_HEADER_SIZE = 12
EXT_HEADER_SIZE = 17
# `decode_header` accepts either; expose the legacy size as the canonical
# minimum for callers that only need a slice big enough to detect the variant.
HEADER_SIZE = EXT_HEADER_SIZE


@dataclass(frozen=True)
class FileHeader:
    pointer_size: int   # 4 or 8
    little_endian: bool
    version: str        # "403", "0501", ...
    header_size: int    # 12 (legacy) or 17 (extended)

    @property
    def endian_char(self) -> str:
        return "<" if self.little_endian else ">"

    @property
    def ptr_fmt(self) -> str:
        return "I" if self.pointer_size == 4 else "Q"


def decode_header(buf: bytes) -> FileHeader:
    if len(buf) < LEGACY_HEADER_SIZE or buf[:7] != HEADER_MAGIC:
        raise ValueError("not a .blend file (missing BLENDER magic)")
    if buf[7:9] == b"17":
        # Extended header.
        if len(buf) < EXT_HEADER_SIZE:
            raise ValueError("truncated extended .blend header")
        ps, en = buf[9:10], buf[12:13]
        version = buf[13:17].decode("ascii", errors="replace")
        hsize = EXT_HEADER_SIZE
    else:
        # Legacy header.
        ps, en = buf[7:8], buf[8:9]
        version = buf[9:12].decode("ascii", errors="replace")
        hsize = LEGACY_HEADER_SIZE
    if ps not in (b"_", b"-"):
        raise ValueError(f"unknown pointer-size byte: {ps!r}")
    if en not in (b"v", b"V"):
        raise ValueError(f"unknown endian byte: {en!r}")
    return FileHeader(
        pointer_size=4 if ps == b"_" else 8,
        little_endian=en == b"v",
        version=version,
        header_size=hsize,
    )


# SDNA decoding ---------------------------------------------------------------
# A DNA1 payload is laid out as:
#   "SDNA"
#   "NAME" + uint32 nnames + nnames null-terminated strings (4-byte aligned)
#   "TYPE" + uint32 ntypes + ntypes null-terminated strings (4-byte aligned)
#   "TLEN" +                ntypes * uint16 sizes          (4-byte aligned)
#   "STRC" + uint32 nstructs + per-struct: uint16 type, uint16 nfields,
#                              nfields * (uint16 type, uint16 name)
# Each section that ends mid-word is padded so the next 4-char magic starts on
# a 4-byte boundary.
#
# Field name strings encode shape: "*foo", "**bar", "verts[3]", "(*func)()".
# We strip pointer/array/function annotations to recover the bare name and the
# size of the field as it lives on disk.


_ARRAY_RE = re.compile(r"\[(\d+)\]")


@dataclass(frozen=True)
class FieldDecl:
    name: str            # bare identifier ("loc")
    raw_name: str        # original ("*next", "loc[3]", "(*func)()")
    type_name: str       # "float", "Object", ...
    type_size: int       # bytes per element (or pointer size if pointer)
    array_len: int       # 1 if scalar, total count if "[a][b]" → a*b
    is_pointer: bool
    is_function_ptr: bool
    offset: int          # byte offset within parent struct
    size: int            # total bytes occupied (type_size * array_len, or ptr_size)


@dataclass(frozen=True)
class StructDecl:
    type_name: str
    size: int
    fields: tuple[FieldDecl, ...]
    by_name: dict[str, FieldDecl] = field(default_factory=dict)


@dataclass
class SDNA:
    header: FileHeader
    names: list[str]
    types: list[str]
    type_sizes: list[int]
    structs: list[StructDecl]
    by_type: dict[str, int] = field(default_factory=dict)  # type name → struct index

    def struct_for(self, type_name: str) -> StructDecl | None:
        idx = self.by_type.get(type_name)
        return None if idx is None else self.structs[idx]


def _read_cstring(buf: bytes, pos: int) -> tuple[str, int]:
    end = buf.index(b"\x00", pos)
    return buf[pos:end].decode("ascii", errors="replace"), end + 1


def _align(pos: int, n: int) -> int:
    rem = pos % n
    return pos if rem == 0 else pos + (n - rem)


def _parse_field_name(raw: str) -> tuple[str, int, bool, bool]:
    """Return (bare_name, array_len, is_pointer, is_function_ptr)."""
    is_func = raw.startswith("(*") and "()" in raw
    is_ptr = is_func or raw.startswith("*")
    name = raw.lstrip("*")
    if is_func:
        # "(*foo)()" → "foo"
        name = name.split("(", 1)[0].lstrip("*").strip("()")
        # Some encodings: "(*foo)(args)"; just take the identifier.
        name = re.sub(r"\W.*", "", name)
        return name, 1, True, True
    array_len = 1
    for m in _ARRAY_RE.finditer(name):
        array_len *= int(m.group(1))
    name = _ARRAY_RE.sub("", name)
    return name, array_len, is_ptr, False


def decode_sdna(payload: bytes, header: FileHeader) -> SDNA:
    """Decode a DNA1 payload into typed tables."""
    if payload[:4] != b"SDNA":
        raise ValueError("DNA1 payload missing 'SDNA' magic")
    end_char = header.endian_char
    pos = 4

    if payload[pos:pos + 4] != b"NAME":
        raise ValueError("DNA1 missing NAME section")
    pos += 4
    (nnames,) = _struct.unpack(end_char + "I", payload[pos:pos + 4])
    pos += 4
    names: list[str] = []
    for _ in range(nnames):
        s, pos = _read_cstring(payload, pos)
        names.append(s)
    pos = _align(pos, 4)

    if payload[pos:pos + 4] != b"TYPE":
        raise ValueError("DNA1 missing TYPE section")
    pos += 4
    (ntypes,) = _struct.unpack(end_char + "I", payload[pos:pos + 4])
    pos += 4
    types: list[str] = []
    for _ in range(ntypes):
        s, pos = _read_cstring(payload, pos)
        types.append(s)
    pos = _align(pos, 4)

    if payload[pos:pos + 4] != b"TLEN":
        raise ValueError("DNA1 missing TLEN section")
    pos += 4
    type_sizes = list(_struct.unpack(end_char + "H" * ntypes, payload[pos:pos + 2 * ntypes]))
    pos += 2 * ntypes
    pos = _align(pos, 4)

    if payload[pos:pos + 4] != b"STRC":
        raise ValueError("DNA1 missing STRC section")
    pos += 4
    (nstructs,) = _struct.unpack(end_char + "I", payload[pos:pos + 4])
    pos += 4

    structs: list[StructDecl] = []
    for _ in range(nstructs):
        type_idx, nfields = _struct.unpack(end_char + "HH", payload[pos:pos + 4])
        pos += 4
        type_name = types[type_idx]
        struct_size = type_sizes[type_idx]
        fields: list[FieldDecl] = []
        offset = 0
        for _f in range(nfields):
            f_type, f_name = _struct.unpack(end_char + "HH", payload[pos:pos + 4])
            pos += 4
            f_type_name = types[f_type]
            raw = names[f_name]
            bare, alen, is_ptr, is_func = _parse_field_name(raw)
            ts = header.pointer_size if is_ptr else type_sizes[f_type]
            size = ts * alen if not is_ptr else header.pointer_size * alen
            fields.append(FieldDecl(
                name=bare, raw_name=raw, type_name=f_type_name,
                type_size=ts, array_len=alen,
                is_pointer=is_ptr, is_function_ptr=is_func,
                offset=offset, size=size,
            ))
            offset += size
        # Note: SDNA does NOT pad inside structs the way a C compiler might;
        # field offsets are tightly packed by SDNA's own rules. The recorded
        # struct_size from TLEN is the authority — if our running offset
        # disagrees we trust TLEN (parity-scope reads are by named field).
        by_name = {fd.name: fd for fd in fields}
        structs.append(StructDecl(
            type_name=type_name, size=struct_size,
            fields=tuple(fields), by_name=by_name,
        ))

    by_type = {s.type_name: i for i, s in enumerate(structs)}
    return SDNA(
        header=header, names=names, types=types,
        type_sizes=type_sizes, structs=structs, by_type=by_type,
    )


__all__ = [
    "FileHeader", "FieldDecl", "StructDecl", "SDNA",
    "HEADER_SIZE", "decode_header", "decode_sdna",
]
