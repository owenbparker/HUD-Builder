"""The names inside a font file (TrueType / OpenType): its PostScript name,
family and full name, read from the font's 'name' table. A design knows a
font by one of these (a Photoshop file by its PostScript name), so HUD
Builder saves a font under its PostScript name and matches layers to it."""

import struct


def names(blob):
    """{"postscript", "family", "full"} (any may be missing); {} if it can't be read
    (a .woff / .woff2, or not a font)."""
    try:
        if blob[:4] == b"ttcf":
            blob_off = struct.unpack(">I", blob[12:16])[0]
        else:
            blob_off = 0
        num = struct.unpack(">H", blob[blob_off + 4:blob_off + 6])[0]
        table = None
        for i in range(num):
            rec = blob_off + 12 + 16 * i
            tag = blob[rec:rec + 4]
            if tag == b"name":
                table = struct.unpack(">I", blob[rec + 8:rec + 12])[0]
                break
        if table is None:
            return {}
        _, count, strings = struct.unpack(">HHH", blob[table:table + 6])
        found = {}
        want = {6: "postscript", 1: "family", 4: "full", 16: "family"}
        for i in range(count):
            rec = table + 6 + 12 * i
            platform, encoding, lang, name_id, length, offset = struct.unpack(">HHHHHH", blob[rec:rec + 12])
            key = want.get(name_id)
            if not key:
                continue
            raw = blob[table + strings + offset:table + strings + offset + length]
            if platform == 3 or platform == 0:
                text = raw.decode("utf-16-be", "ignore")
            elif platform == 1:
                text = raw.decode("latin-1", "ignore")
            else:
                continue
            text = text.strip("\x00 ").strip()
            # (English names first; nameID 16 is the typographic family, better than 1)
            if text and (key not in found or (platform == 3 and lang == 0x409) or name_id == 16):
                found[key] = text
        return found
    except (struct.error, IndexError, ValueError):
        return {}
