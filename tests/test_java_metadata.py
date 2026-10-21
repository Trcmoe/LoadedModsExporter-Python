"""Synthetic class files keep the metadata tests independent of a JDK."""

import struct
import sys
import unittest
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from java_metadata import parse_class


def u1(n):
    return struct.pack(">B", n)


def u2(n):
    return struct.pack(">H", n)


def u4(n):
    return struct.pack(">I", n)


def attribute(name, data):
    return u2(name) + u4(len(data)) + data


def fixture(method_code=None, wide=False):
    cp = []

    def add(tag, body):
        cp.append(u1(tag) + body)
        return len(cp)

    def utf(value):
        raw = value.encode()
        return add(1, u2(len(raw)) + raw)

    cls = utf("example/OldMod")
    cls_ref = add(7, u2(cls))
    obj = utf("java/lang/Object")
    obj_ref = add(7, u2(obj))
    iface = utf("example/Plugin")
    iface_ref = add(7, u2(iface))
    constant_attr = utf("ConstantValue")
    code_attr = utf("Code")
    annotations_attr = utf("RuntimeVisibleAnnotations")
    invisible_attr = utf("RuntimeInvisibleAnnotations")
    field_name = utf("VERSION")
    string_type = utf("Ljava/lang/String;")
    version_text = utf("1.2.3")
    version_ref = add(8, u2(version_text))
    method_name = utf("getName")
    method_type = utf("()Ljava/lang/String;")
    mod_text = utf("Example")
    mod_ref = add(8, u2(mod_text))
    descriptor = utf("Lcpw/mods/fml/common/Mod;")
    name_key = utf("name")
    version_key = utf("version")
    modes_key = utf("modes")
    nested_key = utf("nested")
    enum_type = utf("Lexample/Mode;")
    enum_name = utf("FAST")
    nested_type = utf("Lexample/Nested;")
    bool_key = utf("enabled")
    int_one = add(3, u4(1))
    invisible_type = utf("Lexample/Hidden;")

    field = (u2(0x0019) + u2(field_name) + u2(string_type) + u2(1)
             + attribute(constant_attr, u2(version_ref)))
    code = method_code if method_code is not None else (
        (b"\x13" + u2(mod_ref) if wide else b"\x12" + u1(mod_ref)) + b"\xb0")
    code_body = u2(1) + u2(1) + u4(len(code)) + code + u2(0) + u2(0)
    method = (u2(1) + u2(method_name) + u2(method_type) + u2(1)
              + attribute(code_attr, code_body))
    nested = u2(nested_type) + u2(1) + u2(bool_key) + b"Z" + u2(int_one)
    annotation = (u2(descriptor) + u2(4)
                  + u2(name_key) + b"s" + u2(mod_text)
                  + u2(version_key) + b"s" + u2(version_text)
                  + u2(modes_key) + b"[" + u2(1) + b"e" + u2(enum_type) + u2(enum_name)
                  + u2(nested_key) + b"@" + nested)
    visible = attribute(annotations_attr, u2(1) + annotation)
    hidden = attribute(invisible_attr, u2(1) + u2(invisible_type) + u2(0))
    return (u4(0xCAFEBABE) + u2(0) + u2(61) + u2(len(cp) + 1) + b"".join(cp)
            + u2(0x0021) + u2(cls_ref) + u2(obj_ref)
            + u2(1) + u2(iface_ref) + u2(1) + field + u2(1) + method
            + u2(2) + visible + hidden)


def modern_fixture():
    """A class with two-slot numbers, post-Java-8 pool tags, and an emoji."""
    cp = []

    def add(tag, body, two_slots=False):
        cp.append(u1(tag) + body)
        index = len(cp)
        if two_slots:
            cp.append(None)
        return index

    def utf(value):
        raw = value.encode("utf-8")
        return add(1, u2(len(raw)) + raw)

    name = utf("example/Modern")
    this = add(7, u2(name))
    parent = utf("java/lang/Object")
    parent_ref = add(7, u2(parent))
    constant_attr = utf("ConstantValue")
    code_attr = utf("Code")
    long_name = utf("BUILD")
    long_type = utf("J")
    long_ref = add(5, struct.pack(">q", 2**40), two_slots=True)
    emoji_name = utf("TITLE")
    string_type = utf("Ljava/lang/String;")
    # Java modified UTF-8 encodes U+1F680 as two UTF-16 surrogate sequences.
    emoji_raw = b"Rocket \xed\xa0\xbd\xed\xba\x80"
    emoji_text = add(1, u2(len(emoji_raw)) + emoji_raw)
    emoji_ref = add(8, u2(emoji_text))
    method_name = utf("getBuild")
    method_type = utf("()I")
    int_ref = add(3, u4(42))
    # These entries need parsing even though their values are not inspected.
    module_name = utf("example.module")
    add(19, u2(module_name))
    package_name = utf("example")
    add(20, u2(package_name))
    add(16, u2(method_type))
    name_type = add(12, u2(method_name) + u2(method_type))
    add(17, u2(0) + u2(name_type))
    add(18, u2(0) + u2(name_type))
    add(15, u1(6) + u2(name_type))

    def field(field_name, descriptor, value):
        return (u2(0x0019) + u2(field_name) + u2(descriptor) + u2(1)
                + attribute(constant_attr, u2(value)))

    code = b"\x13" + u2(int_ref) + b"\xac"
    code_body = u2(1) + u2(1) + u4(len(code)) + code + u2(0) + u2(0)
    method = (u2(1) + u2(method_name) + u2(method_type) + u2(1)
              + attribute(code_attr, code_body))
    return (u4(0xCAFEBABE) + u2(0) + u2(61) + u2(len(cp) + 1)
            + b"".join(item or b"" for item in cp)
            + u2(0x0021) + u2(this) + u2(parent_ref) + u2(0)
            + u2(2) + field(long_name, long_type, long_ref)
            + field(emoji_name, string_type, emoji_ref)
            + u2(1) + method + u2(0))


class ClassMetadataTests(unittest.TestCase):
    def test_declarations_and_literal_metadata(self):
        result = parse_class(fixture())
        self.assertEqual(result["name"], "example/OldMod")
        self.assertEqual(result["super"], "java/lang/Object")
        self.assertEqual(result["interfaces"], ["example/Plugin"])
        self.assertEqual(result["constants"], {"VERSION": "1.2.3"})
        self.assertEqual(result["methods"], {"getName": "Example"})
        self.assertEqual(result["annotations"]["Lcpw/mods/fml/common/Mod;"]["name"], "Example")
        self.assertEqual(result["annotations"]["Lcpw/mods/fml/common/Mod;"]["modes"],
                         [{"type": "Lexample/Mode;", "constant": "FAST"}])
        self.assertEqual(result["annotations"]["Lcpw/mods/fml/common/Mod;"]["nested"],
                         {"descriptor": "Lexample/Nested;", "values": {"enabled": True}})
        self.assertIn("Lexample/Hidden;", result["annotations"])

    def test_invalid_input_is_rejected(self):
        data = fixture()
        class_entry = data.index(b"\x07" + u2(1), 10)
        bad_reference = bytearray(data)
        bad_reference[class_entry + 1 : class_entry + 3] = u2(0xffff)
        for invalid in (b"", b"xxxx" + data[4:], data[:-1],
                        data[:-7], data + b"garbage", bytes(bad_reference)):
            with self.subTest(invalid=invalid[:8]):
                with self.assertRaises(ValueError):
                    parse_class(invalid)

    def test_annotation_character_rejects_float_pool_value(self):
        data = fixture().replace(b"\x03\x00\x00\x00\x01", b"\x04\x00\x00\x00\x01")
        data = data.replace(b"Z\x00\x1c", b"C\x00\x1c")
        with self.assertRaises(ValueError):
            parse_class(data)

    def test_modern_pool_and_modified_utf8(self):
        result = parse_class(modern_fixture())
        self.assertEqual(result["constants"], {"BUILD": 2**40, "TITLE": "Rocket 🚀"})
        self.assertEqual(result["methods"], {"getBuild": 42})
        self.assertIn("🚀", json.dumps(result, ensure_ascii=False).encode("utf-8").decode("utf-8"))

    def test_only_literal_return_methods_are_exposed(self):
        self.assertEqual(parse_class(fixture(wide=True))["methods"], {"getName": "Example"})
        # aload_0 is a perfectly valid instruction but requires runtime state.
        self.assertEqual(parse_class(fixture(method_code=b"\x2a\xb0"))["methods"], {})
        # Loading a literal is insufficient if other instructions also run.
        self.assertEqual(parse_class(fixture(method_code=b"\x03\x04\x60\xac"))["methods"], {})


if __name__ == "__main__":
    unittest.main()
