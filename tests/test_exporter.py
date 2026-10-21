import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import LME_Final as lme

SCRIPT = Path(lme.__file__).resolve()


def archive_bytes(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            archive.writestr(name, value)
    return buffer.getvalue()


def class_bytes(name="example/Mod", annotations=None, constants=None, methods=None,
                superclass="java/lang/Object", interfaces=()):
    """Small real class-file fixture, independent of a Java installation."""
    def u2(n):
        return struct.pack(">H", n)
    def u4(n):
        return struct.pack(">I", n)
    pool = []
    def add(tag, raw):
        pool.append(bytes([tag]) + raw)
        return len(pool)
    def utf(text):
        raw = text.encode("utf-8")
        return add(1, u2(len(raw)) + raw)
    def cls(text):
        return add(7, u2(utf(text)))
    def attr(name, raw):
        return u2(utf(name)) + u4(len(raw)) + raw
    this, parent = cls(name), cls(superclass)
    implements = [cls(interface) for interface in interfaces]
    fields = []
    for key, value in (constants or {}).items():
        value_index = add(8, u2(utf(value)))
        fields.append(u2(0x19) + u2(utf(key)) + u2(utf("Ljava/lang/String;")) + u2(1)
                      + attr("ConstantValue", u2(value_index)))
    functions = []
    for key, value in (methods or {}).items():
        value_index = add(8, u2(utf(value)))
        code = b"\x13" + u2(value_index) + b"\xb0"
        body = u2(1) + u2(1) + u4(len(code)) + code + u2(0) + u2(0)
        functions.append(u2(1) + u2(utf(key)) + u2(utf("()Ljava/lang/String;")) + u2(1)
                         + attr("Code", body))
    declarations = []
    for descriptor, values in (annotations or {}).items():
        body = u2(utf(descriptor)) + u2(len(values))
        for key, value in values.items():
            body += u2(utf(key)) + b"s" + u2(utf(value))
        declarations.append(body)
    attributes = [attr("RuntimeVisibleAnnotations", u2(len(declarations)) + b"".join(declarations))]
    return (u4(0xCAFEBABE) + u2(0) + u2(52) + u2(len(pool) + 1) + b"".join(pool)
            + u2(0x21) + u2(this) + u2(parent) + u2(len(implements))
            + b"".join(u2(i) for i in implements) + u2(len(fields)) + b"".join(fields)
            + u2(len(functions)) + b"".join(functions)
            + u2(len(attributes)) + b"".join(attributes))


class ExporterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.mods = self.root / "mods with 空格"
        self.mods.mkdir()
        self.output = self.root / "output"
        self.output.mkdir()
        self.messages = []

    def jar(self, filename, entries):
        destination = self.mods / filename
        destination.parent.mkdir(exist_ok=True, parents=True)
        destination.write_bytes(archive_bytes(entries))
        return destination

    def scan(self, **kwargs):
        return lme.ModScanner(warn=self.messages.append, **kwargs).scan(self.mods)

    def run_cli(self, *args, input=None):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=self.output,
                              input=input, capture_output=True, text=True, encoding="utf-8",
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    def test_json_loaders_extensions_recursion_and_disabled_files(self):
        self.jar("fabric.JAR", {"fabric.mod.json": {"id": "fabric", "name": "织物", "version": "1"}})
        self.jar("sub/quilt.jar", {"quilt.mod.json": {"quilt_loader": {
            "id": "quilt", "version": "2", "metadata": {"name": "Quilt"}}}})
        self.jar("rift.zip", {"riftmod.json": {"id": "rift", "version": "3"}})
        self.jar("lite.litemod", {"litemod.json": {"name": "lite", "displayName": "Lite Mod", "version": "4"}})
        self.jar("disabled.jar.disabled", {"fabric.mod.json": {"id": "disabled", "version": "1"}})
        (self.mods / "config.json").write_text("{}")
        records = self.scan()
        self.assertEqual([m["modid"] for m in records], ["fabric", "lite", "quilt", "rift"])
        self.assertEqual(records[0]["name"], "织物")
        self.assertEqual(records[-1]["name"], "rift")
        self.assertEqual(self.messages, [])

    def test_all_legacy_json_shapes_and_multiple_mods(self):
        self.jar("list.zip", {"mcmod.info": [{"modid": "a", "version": "1"}, {"modid": "b", "version": "2"}]})
        self.jar("wrapper.jar", {"mcmod.info": {"modinfoversion": 2, "modlist": [
            {"modid": "c", "version": "3"}, {"modid": "d", "version": "4"}]}})
        self.jar("single.jar", {"mcmod.info": {"modid": "e", "version": "5"}})
        self.assertEqual([m["modid"] for m in self.scan()], list("abcde"))

    def test_multiple_toml_mods_properties_and_folded_manifest(self):
        self.jar("forge.jar", {"META-INF/mods.toml": '[properties]\nrelease="7.8"\n[[mods]]\nmodId="first"\nversion="${file.jarVersion}"\n[[mods]]\nmodId="second"\nversion="${file.release}"\n',
            "META-INF/MANIFEST.MF": "Manifest-Version: 1.0\r\nImplementation-Version: 1.2.\r\n 3+build\r\n\r\nName: Other\r\nImplementation-Version: wrong\r\n"})
        self.assertEqual([r["version"] for r in self.scan()], ["1.2.3+build", "7.8"])

    def test_current_metadata_precedes_legacy_and_compatibility(self):
        self.jar("neo.jar", {"META-INF/neoforge.mods.toml": '[[mods]]\nmodId="neo"\nversion="1"',
            "META-INF/mods.toml": '[[mods]]\nmodId="forge"\nversion="2"',
            "mcmod.info": [{"modid": "old", "version": "3"}]})
        self.jar("quilt.jar", {"quilt.mod.json": {"quilt_loader": {"id": "quilt", "version": "4"}},
            "fabric.mod.json": {"id": "compatibility", "version": "5"}})
        self.assertEqual([r["modid"] for r in self.scan()], ["neo", "quilt"])

    def test_json_comments_and_trailing_commas_preserve_strings(self):
        raw = '\ufeff{/* comment */"url":"https://example.org/a//b", // comment\n"name":"a,} \\\" /* literal */", "lines":"one\\ntwo", "items":[1,2,],}'
        data = lme.load_json(raw)
        self.assertEqual(data["url"], "https://example.org/a//b")
        self.assertEqual(data["name"], 'a,} " /* literal */')
        self.assertEqual(data["lines"], "one\ntwo")
        self.assertEqual(data["items"], [1, 2])

    def test_broken_archives_and_descriptors_do_not_stop_scan(self):
        (self.mods / "bad.jar").write_bytes(b"not a zip")
        self.jar("bad-json.jar", {"fabric.mod.json": "{"})
        self.jar("bad-quilt.jar", {"quilt.mod.json": {"quilt_loader": []}})
        self.jar("bad-toml.jar", {"META-INF/mods.toml": "[[mods]", "mcmod.info": {"modid": "fallback", "version": "1"}})
        self.jar("valid.jar", {"fabric.mod.json": {"id": "valid", "version": "2"}})
        self.assertEqual([r["modid"] for r in self.scan()], ["fallback", "valid"])
        self.assertTrue(any("bad.jar" in m for m in self.messages))
        self.assertTrue(any("bad-json.jar" in m for m in self.messages))

    def test_declared_nested_mods_only_and_no_aliases(self):
        grandchild = archive_bytes({"fabric.mod.json": {"id": "grandchild", "version": "3"}})
        child = archive_bytes({"fabric.mod.json": {"id": "child", "version": "2", "jars": [{"file": "g.jar"}]}, "g.jar": grandchild})
        self.jar("parent.jar", {"fabric.mod.json": {"id": "parent", "version": "1", "provides": ["alias"],
            "jars": [{"file": "c.jar"}, {"file": "library.jar"}]}, "c.jar": child,
            "library.jar": archive_bytes({"README.txt": "library"}),
            "undeclared.jar": archive_bytes({"fabric.mod.json": {"id": "hidden", "version": "4"}})})
        self.assertEqual([r["modid"] for r in self.scan()], ["child", "grandchild", "parent"])
        self.assertEqual(self.messages, [])
        self.assertEqual([r["modid"] for r in self.scan(include_nested=False)], ["parent"])

    def test_quilt_jarjar_and_legacy_contained_dependencies(self):
        child = archive_bytes({"fabric.mod.json": {"id": "child", "version": "1"}})
        self.jar("quilt.jar", {"quilt.mod.json": {"quilt_loader": {"id": "q", "version": "1", "jars": ["child.jar"]}}, "child.jar": child})
        self.jar("forge.jar", {"META-INF/mods.toml": '[[mods]]\nmodId="f"\nversion="1"',
            "META-INF/jarjar/metadata.json": {"jars": [{"path": "nested/child.jar"}]}, "nested/child.jar": child})
        self.jar("legacy.jar", {"mcmod.info": {"modid": "legacy", "version": "1"},
            "META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nContainedDeps: child.jar\n", "META-INF/libraries/child.jar": child})
        self.assertEqual([r["modid"] for r in self.scan()], ["child", "f", "legacy", "q"])

    def test_top_level_version_wins_over_nested_conflict(self):
        self.jar("a-parent.jar", {"fabric.mod.json": {"id": "parent", "version": "1", "jars": [{"file": "child.jar"}]},
            "child.jar": archive_bytes({"fabric.mod.json": {"id": "child", "version": "old"}})})
        self.jar("z-child.jar", {"fabric.mod.json": {"id": "child", "version": "new"}})
        self.assertEqual(self.scan()[0]["version"], "new")
        self.assertTrue(any("old" in m and "new" in m for m in self.messages))

    def test_missing_and_oversized_nested_files_preserve_parent(self):
        self.jar("parent.jar", {"fabric.mod.json": {"id": "parent", "version": "1", "jars": [
            {"file": "missing.jar"}, {"file": "big.jar"}]}, "big.jar": b"x" * 32})
        with patch.object(lme, "MAX_NESTED_SIZE", 16):
            self.assertEqual([r["modid"] for r in self.scan()], ["parent"])
        self.assertEqual(len(self.messages), 2)

    def test_legacy_annotation_identity_name_and_version_precedence(self):
        def annotated(modid, version=""):
            return class_bytes(annotations={lme.MOD_ANNOTATIONS[0]: {
                "modid": modid, "name": "Annotation Name", "version": version}})
        self.jar("old.jar", {"mcmod.info": [{"modid": "real", "name": "Metadata Name", "version": "metadata"},
            {"modid": "orphan", "version": "unused"}], "example/Mod.class": annotated("real", "annotation"),
            "version.properties": "real.version=property\n"})
        self.jar("property.jar", {"example/Mod.class": annotated("property"),
            "version.properties": "property.version = 2.\\\n  5\n"})
        self.jar("default.jar", {"example/Mod.class": annotated("default")})
        records = {r["modid"]: r for r in self.scan()}
        self.assertNotIn("orphan", records)
        self.assertEqual(records["real"], {"modid": "real", "name": "Metadata Name", "version": "annotation"})
        self.assertEqual(records["property"]["version"], "2.5")
        self.assertEqual(records["default"]["version"], "1.0")

    def test_declared_annotation_only_nested_mod(self):
        child = archive_bytes({"example/Mod.class": class_bytes(annotations={
            lme.MOD_ANNOTATIONS[1]: {"modid": "annotation", "version": "2"}})})
        self.jar("parent.jar", {"mcmod.info": {"modid": "parent", "version": "1"},
            "META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nContainedDeps: child.jar\n", "META-INF/libraries/child.jar": child})
        self.assertEqual([r["modid"] for r in self.scan()], ["annotation", "parent"])

    def test_special_mods_and_old_literal_getters(self):
        self.jar("renamed-opti.jar", {"optifine/Installer.class": b"marker",
            "Config.class": class_bytes(constants={"VERSION": "OptiFine_1.12.2_HD_U_G6_pre1"})})
        self.jar("renamed-better.jar", {"guichaguri/betterfps/BetterFps.class": b"marker",
            "META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nTweakVersion: 1.4.8\nTweakName: BetterFps\n"})
        self.jar("old.zip", {"mod_Old.class": class_bytes(name="mod_Old", superclass="BaseMod", methods={"Version": "1.5"})})
        self.jar("lite.jar", {"LiteModExample.class": class_bytes(name="LiteModExample",
            interfaces=["com/mumfrey/liteloader/LiteMod"], methods={"getName": "Lite Example", "getVersion": "2.0"})})
        records = {r["modid"]: r for r in self.scan()}
        self.assertEqual(records["OptiFine"]["version"], "OptiFine_1.12.2_HD_U_G6_pre1")
        self.assertEqual(records["betterfps"]["version"], "1.4.8")
        self.assertEqual(records["mod_Old"]["version"], "1.5")
        self.assertEqual(records["example"]["name"], "Lite Example")

    def test_ignore_exporter_itself_and_custom_mods(self):
        for modid in ("loadedmodsexporter", "ignore", "keep"):
            self.jar(f"{modid}.jar", {"fabric.mod.json": {"id": modid, "version": "1"}})
        self.assertEqual([r["modid"] for r in self.scan(ignored=["ignore"])], ["keep"])

    def test_cli_current_working_directory_and_fresh_exports(self):
        mod = self.jar("first.jar", {"fabric.mod.json": {"id": "first", "name": "中文", "version": "1"}})
        result = self.run_cli(self.mods)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.output / "lme_export.json"
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))[0]["name"], "中文")
        self.assertFalse((self.mods / output.name).exists())
        mod.unlink()
        result = self.run_cli(self.mods)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output.read_text()), [])
        self.assertEqual(list(self.output.glob("*.tmp")), [])

    def test_interactive_quoted_path_and_compact_output(self):
        self.jar("f.jar", {"fabric.mod.json": {"id": "f", "version": "1"}})
        result = self.run_cli("--compact", input=f'"{self.mods}"\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.output / "lme_export.json").read_text(), '[{"modid":"f","name":"f","version":"1"}]\n')

    def test_invalid_path_does_not_replace_existing_export(self):
        output = self.output / "lme_export.json"
        output.write_text("previous")
        result = self.run_cli(self.root / "missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_text(), "previous")

    def test_existing_malformed_output_is_replaced(self):
        output = self.output / "lme_export.json"
        output.write_text("{bad json")
        result = self.run_cli(self.mods)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output.read_text()), [])

    def test_failed_atomic_replace_preserves_previous_file_and_cleans_temp(self):
        output = self.output / "lme_export.json"
        output.write_text("previous")
        with patch.object(lme.Path, "cwd", return_value=self.output), \
                patch.object(lme.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                lme.export_mods(self.mods)
        self.assertEqual(output.read_text(), "previous")
        self.assertEqual(list(self.output.glob(".lme_export-*.tmp")), [])

    def test_nested_depth_limit_reports_and_preserves_readable_mods(self):
        inner = archive_bytes({"fabric.mod.json": {"id": "inner", "version": "1"}})
        child = archive_bytes({"fabric.mod.json": {"id": "child", "version": "1", "jars": [
            {"file": "inner.jar"}]}, "inner.jar": inner})
        self.jar("parent.jar", {"fabric.mod.json": {"id": "parent", "version": "1", "jars": [
            {"file": "child.jar"}]}, "child.jar": child})
        with patch.object(lme, "MAX_NESTED_DEPTH", 1):
            self.assertEqual([r["modid"] for r in self.scan()], ["child", "parent"])
        self.assertEqual(len(self.messages), 1)


if __name__ == "__main__":
    unittest.main()
