"""Figma's file format: a .fig is a zip of canvas.fig (and images/), and
canvas.fig is "fig-kiwi": a kiwi schema and a message in that schema, each
compressed (deflate, or zstandard in newer files). read_fig() gives the message
as plain dicts and lists."""

import struct
import zlib

KINDS = {0: "enum", 1: "struct", 2: "message"}
BUILTIN = {-1: "bool", -2: "byte", -3: "int", -4: "uint", -5: "float", -6: "string", -7: "int64", -8: "uint64"}


class Reader:
    """kiwi's encodings: varints, its packed floats, nul-ended strings."""

    def __init__(self, data):
        self.b, self.o = data, 0

    def byte(self):
        v = self.b[self.o]
        self.o += 1
        return v

    def uint(self):
        v = shift = 0
        while True:
            c = self.byte()
            v |= (c & 127) << shift
            shift += 7
            if not c & 128 or shift >= 35:
                return v

    def uint64(self):
        v = shift = 0
        while True:
            c = self.byte()
            if shift == 56:
                return v | c << shift
            v |= (c & 127) << shift
            shift += 7
            if not c & 128:
                return v

    def int(self):
        v = self.uint()
        return ~(v >> 1) if v & 1 else v >> 1

    def int64(self):
        v = self.uint64()
        return ~(v >> 1) if v & 1 else v >> 1

    def float(self):
        first = self.byte()
        if first == 0:
            return 0.0
        bits = first | self.byte() << 8 | self.byte() << 16 | self.byte() << 24
        bits = ((bits << 23) | (bits >> 9)) & 0xFFFFFFFF
        return struct.unpack("<f", struct.pack("<I", bits))[0]

    def string(self):
        end = self.b.index(0, self.o)
        text = self.b[self.o:end].decode("utf-8", "replace")
        self.o = end + 1
        return text


def schema(data):
    """[(name, kind, [(field, type, is_array, value)])]."""
    r, defs = Reader(data), []
    for _ in range(r.uint()):
        name = r.string()
        kind = KINDS[r.byte()]
        fields = []
        for _ in range(r.uint()):
            fields.append((r.string(), r.int(), bool(r.byte()), r.uint()))
        defs.append((name, kind, fields))
    return defs


def decode(defs, data, root="Message"):
    r = Reader(data)
    index = {d[0]: i for i, d in enumerate(defs)}
    plain = {"bool": lambda: bool(r.byte()), "byte": r.byte, "int": r.int, "uint": r.uint, "float": r.float,
             "string": r.string, "int64": r.int64, "uint64": r.uint64}
    by_value = [{f[3]: f for f in d[2]} for d in defs]

    def one(t):
        if t < 0:
            return plain[BUILTIN[t]]()
        name, kind, fields = defs[t]
        if kind == "enum":
            v = r.uint()
            return by_value[t][v][0] if v in by_value[t] else v
        if kind == "struct":
            return {f[0]: value(f) for f in fields}
        out = {}
        while True:
            v = r.uint()
            if v == 0:
                return out
            f = by_value[t][v]
            out[f[0]] = value(f)

    def value(f):
        if not f[2]:
            return one(f[1])
        n = r.uint()
        if f[1] == -2:       # (a byte array)
            d = bytes(r.b[r.o:r.o + n])
            r.o += n
            return d
        return [one(f[1]) for _ in range(n)]

    return one(index[root])


def _unpack(chunk):
    if chunk[:4] == b"\x28\xb5\x2f\xfd":
        try:
            import zstandard
        except ImportError:
            raise ValueError("Reading this Figma file needs the zstandard package")
        return zstandard.ZstdDecompressor().decompress(chunk, max_output_size=1 << 30)
    try:
        return zlib.decompress(chunk, -15)
    except zlib.error:
        return zlib.decompress(chunk)


def read_fig(canvas):
    """canvas.fig's bytes as the decoded message ({"nodeChanges": [...], "blobs": [...]})."""
    if canvas[:8] not in (b"fig-kiwi", b"fig-jam."):
        raise ValueError("That isn't a Figma file")
    o, chunks = 12, []
    while o + 4 <= len(canvas):
        n = struct.unpack("<I", canvas[o:o + 4])[0]
        chunks.append(canvas[o + 4:o + 4 + n])
        o += 4 + n
    if len(chunks) < 2:
        raise ValueError("That Figma file is damaged")
    try:
        return decode(schema(_unpack(chunks[0])), _unpack(chunks[1]))
    except (IndexError, KeyError, struct.error, zlib.error, UnicodeDecodeError) as e:
        raise ValueError(f"That Figma file can't be read ({e})")
