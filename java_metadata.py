"""Small, non-executing Java class-file metadata reader.

Only declarations, annotation values, ConstantValue fields, and methods consisting
of a single literal load and return are exposed. No bytecode is executed.
"""

from __future__ import annotations

import struct


class _Reader:
    def __init__(self, data: bytes | memoryview):
        self.data = memoryview(data)
        self.pos = 0

    def take(self, size: int) -> bytes:
        if size < 0 or size > len(self.data) - self.pos:
            raise ValueError("truncated class file")
        result = self.data[self.pos : self.pos + size].tobytes()
        self.pos += size
        return result

    def u1(self) -> int:
        return self.take(1)[0]

    def u2(self) -> int:
        return int.from_bytes(self.take(2), "big")

    def u4(self) -> int:
        return int.from_bytes(self.take(4), "big")


def parse_class(data: bytes) -> dict:
    """Return static metadata from one JVM class file, or raise ValueError.

    Names use JVM internal slash notation. Enum annotation values are represented
    as ``{'type': descriptor, 'constant': name}``; nested annotations have a
    ``descriptor`` and ``values`` mapping.
    """
    if not isinstance(data, bytes):
        raise ValueError("class data must be bytes")
    reader = _Reader(data)
    if reader.u4() != 0xCAFEBABE:
        raise ValueError("invalid class-file magic")
    reader.u2()  # minor
    reader.u2()  # major; newer versions retain this metadata format
    count = reader.u2()
    pool: list[tuple[int, object] | None] = [None] * count
    index = 1
    while index < count:
        tag = reader.u1()
        if tag == 1:  # modified UTF-8; encoded NUL is the relevant difference here
            raw = reader.take(reader.u2()).replace(b"\xc0\x80", b"\x00")
            try:
                decoded = raw.decode("utf-8", "surrogatepass")
                # Modified UTF-8 stores supplementary characters as two UTF-8
                # encoded UTF-16 surrogates. Combine valid pairs for JSON output.
                value = decoded.encode("utf-16-be", "surrogatepass").decode("utf-16-be")
            except UnicodeError as exc:
                raise ValueError("invalid constant-pool UTF-8") from exc
        elif tag in (3, 4):
            raw = reader.take(4)
            value = struct.unpack(">i" if tag == 3 else ">f", raw)[0]
        elif tag in (5, 6):
            raw = reader.take(8)
            value = struct.unpack(">q" if tag == 5 else ">d", raw)[0]
        elif tag in (7, 8, 16, 19, 20):
            value = reader.u2()
        elif tag in (9, 10, 11, 12, 17, 18):
            value = (reader.u2(), reader.u2())
        elif tag == 15:
            value = (reader.u1(), reader.u2())
        else:
            raise ValueError(f"unsupported constant-pool tag {tag}")
        pool[index] = (tag, value)
        if tag in (5, 6):
            index += 1  # long/double reserve the next entry
        index += 1

    def entry(n: int, expected: int | tuple[int, ...]) -> object:
        if not 0 < n < count or pool[n] is None:
            raise ValueError("invalid constant-pool index")
        tag, value = pool[n]
        if tag not in ((expected,) if isinstance(expected, int) else expected):
            raise ValueError("unexpected constant-pool entry")
        return value

    def utf(n: int) -> str:
        return entry(n, 1)  # type: ignore[return-value]

    def class_name(n: int) -> str | None:
        return utf(entry(n, 7)) if n else None  # type: ignore[arg-type]

    def constant(n: int) -> object:
        value = entry(n, (3, 4, 5, 6, 8))
        return utf(value) if pool[n][0] == 8 else value  # type: ignore[arg-type,index]

    def element(r: _Reader, depth: int = 0) -> object:
        if depth > 32:
            raise ValueError("annotation nesting too deep")
        tag = chr(r.u1())
        if tag in "BCDFIJSZs":
            n = r.u2()
            if tag == "s":
                return utf(n)
            # Annotation primitives have stricter pool types than ldc. Reject
            # corrupt values here so callers always receive ValueError.
            value = entry(n, {"D": 6, "F": 4, "J": 5}.get(tag, 3))
            if tag == "Z":
                return bool(value)
            if tag == "C":
                if not 0 <= value <= 0xFFFF:
                    raise ValueError("invalid annotation character")
                return chr(value)  # type: ignore[arg-type]
            return value
        if tag == "e":
            return {"type": utf(r.u2()), "constant": utf(r.u2())}
        if tag == "c":
            return utf(r.u2())
        if tag == "@":
            descriptor, values = annotation(r, depth + 1)
            return {"descriptor": descriptor, "values": values}
        if tag == "[":
            return [element(r, depth + 1) for _ in range(r.u2())]
        raise ValueError("invalid annotation element tag")

    def annotation(r: _Reader, depth: int = 0) -> tuple[str, dict]:
        descriptor = utf(r.u2())
        values = {utf(r.u2()): element(r, depth) for _ in range(r.u2())}
        return descriptor, values

    def attributes(r: _Reader, number: int) -> list[tuple[str, bytes]]:
        return [(utf(r.u2()), r.take(r.u4())) for _ in range(number)]

    def simple_return(code: bytes) -> object | None:
        r = _Reader(code)
        try:
            op = r.u1()
            if op == 0x12:  # ldc
                value = constant(r.u1())
            elif op in (0x13, 0x14):  # ldc_w / ldc2_w
                value = constant(r.u2())
            elif 0x02 <= op <= 0x08:  # iconst_m1 .. iconst_5
                value = op - 3
            elif op == 0x10:
                value = struct.unpack(">b", r.take(1))[0]
            elif op == 0x11:
                value = struct.unpack(">h", r.take(2))[0]
            else:
                return None
            if r.u1() not in (0xAC, 0xAD, 0xAE, 0xAF, 0xB0) or r.pos != len(code):
                return None
            return value
        except ValueError:
            return None

    reader.u2()  # access flags
    name = class_name(reader.u2())
    if name is None:
        raise ValueError("missing class name")
    super_name = class_name(reader.u2())
    interfaces = [class_name(reader.u2()) for _ in range(reader.u2())]
    if any(interface is None for interface in interfaces):
        raise ValueError("missing interface name")
    constants: dict[str, object] = {}
    for _ in range(reader.u2()):
        reader.u2()  # access
        field_name = utf(reader.u2())
        reader.u2()  # descriptor
        for attr_name, body in attributes(reader, reader.u2()):
            if attr_name == "ConstantValue":
                part = _Reader(body)
                value = constant(part.u2())
                if part.pos != len(body):
                    raise ValueError("invalid ConstantValue attribute")
                constants[field_name] = value

    methods: dict[str, object] = {}
    for _ in range(reader.u2()):
        reader.u2()  # access
        method_name = utf(reader.u2())
        reader.u2()  # descriptor
        for attr_name, body in attributes(reader, reader.u2()):
            if attr_name == "Code":
                part = _Reader(body)
                part.u2()  # max stack
                part.u2()  # max locals
                code = part.take(part.u4())
                part.take(part.u2() * 8)  # exception table
                attributes(part, part.u2())  # nested code attributes
                if part.pos != len(body):
                    raise ValueError("invalid Code attribute")
                value = simple_return(code)
                if value is not None:
                    methods[method_name] = value

    annotations: dict[str, dict] = {}
    for attr_name, body in attributes(reader, reader.u2()):
        if attr_name in ("RuntimeVisibleAnnotations", "RuntimeInvisibleAnnotations"):
            part = _Reader(body)
            for _ in range(part.u2()):
                descriptor, values = annotation(part)
                annotations[descriptor] = values
            if part.pos != len(body):
                raise ValueError("invalid annotations attribute")
    if reader.pos != len(data):
        raise ValueError("trailing class-file bytes")
    return {"name": name, "super": super_name, "interfaces": interfaces,
            "annotations": annotations, "constants": constants, "methods": methods}
