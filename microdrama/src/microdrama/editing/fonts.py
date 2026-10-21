"""Thai-safe font handling for burned-in captions (T015).

Thai text needs a font that actually covers the Thai block (base consonants, vowels
and the combining marks U+0E31, U+0E34-U+0E3A, U+0E47-U+0E4E) AND a shaping engine:
plain ``drawtext`` (FreeType only) stacks Thai marks incorrectly, so burns go through
the libass ``subtitles`` filter with an explicitly resolved font file. Nothing is
guessed from vendor marketing: coverage is verified by parsing the font's own cmap
table, and a missing font is a typed finding with the burn skipped — never tofu.

Pure-Python SFNT parsing (table directory, cmap formats 4/12/6, name table) keeps
this offline and dependency-free; no fontTools dependency is added.
"""

from __future__ import annotations

import struct
from pathlib import Path

from microdrama.editing.config import EditingConfig
from microdrama.editing.models import FontResolution

_FONT_SUFFIXES = frozenset({".ttf", ".otf", ".ttc"})
_DEFAULT_FONT_DIRS = ("/usr/share/fonts", "/usr/local/share/fonts")

# Codepoints every Thai-capable font must cover before any caption text is checked:
# the Thai block's assigned core (consonants, independent vowels, marks, digits,
# punctuation). Tofu in ANY of these means the font is not Thai-safe.
THAI_REQUIRED_CODEPOINTS: frozenset[int] = frozenset(
    [*range(0x0E01, 0x0E3B), *range(0x0E3F, 0x0E4F), *range(0x0E50, 0x0E5A)]
)


class FontFileError(ValueError):
    """The candidate file is not a readable SFNT font (skipped, not fatal)."""


def _read_table(data: bytes, tag: bytes) -> bytes | None:
    if len(data) < 12:
        raise FontFileError("file too short for an SFNT header")
    num_tables = struct.unpack_from(">H", data, 4)[0]
    if len(data) < 12 + 16 * num_tables:
        raise FontFileError("truncated table directory")
    for index in range(num_tables):
        offset = 12 + 16 * index
        entry_tag = data[offset : offset + 4]
        if entry_tag != tag:
            continue
        _checksum, off, length = struct.unpack_from(">III", data, offset + 4)
        if off + length > len(data):
            raise FontFileError(f"{tag.decode('ascii', 'replace')} table out of range")
        return data[off : off + length]
    return None


def font_codepoints(data: bytes) -> frozenset[int]:
    """Every Unicode codepoint the font's cmap maps to a glyph."""
    cmap = _read_table(data, b"cmap")
    if cmap is None or len(cmap) < 4:
        raise FontFileError("no cmap table")
    num_subtables = struct.unpack_from(">H", cmap, 2)[0]
    covered: set[int] = set()
    for index in range(num_subtables):
        entry = 4 + 8 * index
        if entry + 8 > len(cmap):
            raise FontFileError("truncated cmap subtable directory")
        platform, encoding, offset = struct.unpack_from(">HHI", cmap, entry)
        sub = cmap[offset:]
        if len(sub) < 2:
            raise FontFileError("truncated cmap subtable")
        fmt = struct.unpack_from(">H", sub, 0)[0]
        if fmt == 4:
            covered.update(_cmap_format4(sub))
        elif fmt == 12:
            covered.update(_cmap_format12(sub))
        elif fmt == 6:
            covered.update(_cmap_format6(sub))
        del platform, encoding  # any subtable is a valid coverage witness
    return frozenset(covered)


def _cmap_format4(sub: bytes) -> set[int]:
    if len(sub) < 14:
        raise FontFileError("truncated format-4 subtable")
    seg_count = struct.unpack_from(">H", sub, 6)[0] // 2
    end_off = 14
    start_off = end_off + 2 * seg_count + 2
    out: set[int] = set()
    for seg in range(seg_count):
        end_code = struct.unpack_from(">H", sub, end_off + 2 * seg)[0]
        start_code = struct.unpack_from(">H", sub, start_off + 2 * seg)[0]
        if start_code == 0xFFFF:
            continue
        out.update(range(start_code, min(end_code, 0xFFFE) + 1))
    return out


def _cmap_format6(sub: bytes) -> set[int]:
    if len(sub) < 10:
        raise FontFileError("truncated format-6 subtable")
    first, count = struct.unpack_from(">HH", sub, 6)
    return set(range(first, first + count))


def _cmap_format12(sub: bytes) -> set[int]:
    if len(sub) < 16:
        raise FontFileError("truncated format-12 subtable")
    num_groups = struct.unpack_from(">I", sub, 12)[0]
    out: set[int] = set()
    for group in range(num_groups):
        offset = 16 + 12 * group
        if offset + 12 > len(sub):
            raise FontFileError("truncated format-12 group")
        start, end, _glyph = struct.unpack_from(">III", sub, offset)
        out.update(range(start, end + 1))
    return out


def font_family_name(data: bytes) -> str | None:
    """Family name (name id 1) from the name table; None when unreadable."""
    name = _read_table(data, b"name")
    if name is None or len(name) < 6:
        return None
    count, string_offset = struct.unpack_from(">HH", name, 2)
    for index in range(count):
        entry = 6 + 12 * index
        if entry + 12 > len(name):
            return None
        platform, _encoding, _langid, name_id, length, offset = struct.unpack_from(
            ">HHHHHH", name, entry
        )
        if name_id != 1:
            continue
        pos = string_offset + offset
        raw = name[pos : pos + length]
        if platform in (0, 3):  # Unicode / Windows: UTF-16BE
            return raw.decode("utf-16-be", "replace").strip("\x00") or None
        return raw.decode("mac-roman", "replace").strip("\x00") or None
    return None


def _candidate_files(config: EditingConfig) -> list[tuple[int, Path]]:
    """(family_rank, path) for every readable candidate font, deterministically."""
    dirs: list[str] = []
    for directory in (*config.font_dirs, *_DEFAULT_FONT_DIRS):
        if directory not in dirs:
            dirs.append(directory)
    families = list(config.font_candidates)
    found: list[tuple[int, Path]] = []
    seen: set[Path] = set()
    for directory in dirs:
        root = Path(directory)
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _FONT_SUFFIXES:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            stem_lower = path.stem.lower()
            for rank, family in enumerate(families):
                if stem_lower == family.lower() or stem_lower.startswith(family.lower() + "-"):
                    found.append((rank, path))
                    break
    # Prefer the plain face (stem == family) over styled ones (Loma before Loma-Bold),
    # then the earlier candidate family, then the path: fully deterministic order.
    found.sort(
        key=lambda item: (item[0], 0 if _is_plain_face(item[1], families) else 1, str(item[1]))
    )
    return found


def _is_plain_face(path: Path, families: list[str]) -> bool:
    stem = path.stem.lower()
    return any(stem == family.lower() for family in families)


def covers_text(covered: frozenset[int], texts: list[str]) -> bool:
    """True when every non-whitespace character of every text has a glyph."""
    needed = {ord(ch) for text in texts for ch in text if not ch.isspace()}
    return needed <= covered


def resolve_caption_font(config: EditingConfig, texts: list[str]) -> FontResolution:
    """First Thai-safe candidate that covers every caption text, deterministically.

    A candidate qualifies only if its cmap covers the required Thai core codepoints
    AND all characters actually used by the cues (Thai or Latin). The family returned
    is the font's own name-table family (what libass must be told), never a guess
    from the file name.
    """
    searched = 0
    for _rank, path in _candidate_files(config):
        searched += 1
        try:
            data = path.read_bytes()
            covered = font_codepoints(data)
            if not THAI_REQUIRED_CODEPOINTS <= covered:
                continue
            if not covers_text(covered, texts):
                continue
            family = font_family_name(data) or path.stem
        except (FontFileError, OSError):
            continue
        return FontResolution(
            family=family, path=str(path.resolve()), coverage_ok=True, searched=searched
        )
    return FontResolution(
        family=config.font_candidates[0], path=None, coverage_ok=False, searched=searched
    )


__all__ = [
    "THAI_REQUIRED_CODEPOINTS",
    "FontFileError",
    "covers_text",
    "font_codepoints",
    "font_family_name",
    "resolve_caption_font",
]
