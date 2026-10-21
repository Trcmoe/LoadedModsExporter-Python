"""Export Minecraft Java mod metadata without loading or executing the mods."""

import argparse
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import zipfile
import zlib

from java_metadata import parse_class


OUTPUT_NAME = "lme_export.json"
ARCHIVE_SUFFIXES = {".jar", ".zip", ".litemod"}
MAX_METADATA_SIZE = 4 * 1024 * 1024
MAX_CLASS_SIZE = 16 * 1024 * 1024
MAX_NESTED_SIZE = 128 * 1024 * 1024
MAX_NESTED_TOTAL = 512 * 1024 * 1024
MAX_NESTED_DEPTH = 8
MOD_ANNOTATIONS = ("Lcpw/mods/fml/common/Mod;", "Lnet/minecraftforge/fml/common/Mod;")
READ_ERRORS = (OSError, ValueError, KeyError, RuntimeError, NotImplementedError,
               zipfile.BadZipFile, EOFError, RecursionError, zlib.error)


def load_json(raw):
    """Accept legacy JSON comments/trailing commas without damaging quoted text."""
    source = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw.lstrip("\ufeff")
    cleaned = []
    quoted = escaped = False
    i = 0
    while i < len(source):
        char = source[i]
        if quoted:
            cleaned.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
            cleaned.append(char)
        elif source.startswith("//", i):
            end = source.find("\n", i + 2)
            i = len(source) if end < 0 else end
            cleaned.append("\n")
            continue
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end < 0:
                raise ValueError("未结束的 JSON 注释")
            cleaned.append(" ")
            i = end + 2
            continue
        else:
            cleaned.append(char)
        i += 1
    text = "".join(cleaned)
    cleaned = []
    quoted = escaped = False
    for i, char in enumerate(text):
        if not quoted and char == ",":
            tail = i + 1
            while tail < len(text) and text[tail].isspace():
                tail += 1
            if tail < len(text) and text[tail] in "]}":
                continue
        cleaned.append(char)
        if escaped:
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
    return json.loads("".join(cleaned), strict=False)


def text_value(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def record(modid, name="", version=""):
    return {"modid": text_value(modid), "name": text_value(name),
            "version": text_value(version)}


def read_entry(archive, name, limit=MAX_METADATA_SIZE):
    if archive.getinfo(name).file_size > limit:
        raise ValueError(f"{name} 超过读取上限 ({limit} 字节)")
    with archive.open(name) as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"{name} 超过读取上限")
    return raw


def read_manifest(raw):
    """Read only the main manifest section, including folded continuation lines."""
    result = {}
    key = None
    for line in raw.decode("utf-8-sig").splitlines():
        if not line:
            break
        if line.startswith(" ") and key:
            result[key] += line[1:]
        elif ": " in line:
            key, value = line.split(": ", 1)
            key = key.lower()
            result[key] = value
    return result


def legacy_records(data):
    if isinstance(data, dict):
        data = data.get("modlist", [data])
    if not isinstance(data, list):
        raise ValueError("mcmod.info 应为对象、列表或包含 modlist 的对象")
    return [record(item.get("modid"), item.get("name"), item.get("version"))
            for item in data if isinstance(item, dict)]


def read_version_properties(raw):
    """Read the version properties used by legacy FML (Java's Latin-1 format)."""
    properties = {}
    continued = ""
    for line in raw.decode("latin-1").splitlines():
        line = continued + line.lstrip()
        if (len(line) - len(line.rstrip("\\"))) % 2:
            continued = line[:-1]
            continue
        continued = ""
        if not line or line.startswith(("#", "!")):
            continue
        parts = re.split(r"(?<!\\)[=: \t]", line, maxsplit=1)
        key = parts[0]
        value = parts[1].lstrip(" \t=:") if len(parts) > 1 else ""
        def unescape(text):
            return re.sub(r"\\u([0-9a-fA-F]{4})|\\(.)",
                          lambda m: chr(int(m[1], 16)) if m[1] else
                          {"t": "\t", "n": "\n", "r": "\r", "f": "\f"}.get(m[2], m[2]), text)
        properties[unescape(key)] = unescape(value)
    return properties


class ModScanner:
    def __init__(self, include_nested=True, ignored=(), warn=None):
        self.include_nested = include_nested
        self.ignored = {"loadedmodsexporter", *ignored}
        self.warn = warn or (lambda message: print(f"警告：{message}", file=sys.stderr))
        self.records = {}
        self.sources = {}
        self.warning_count = 0
        self.archive_count = 0
        self.nested_bytes = 0
        self.nested_count = 0

    def warning(self, message):
        self.warning_count += 1
        self.warn(message)

    def add(self, item, source):
        modid = item["modid"]
        if not modid or modid in self.ignored:
            return
        item = dict(item)
        item["name"] = item["name"] or modid
        previous = self.records.get(modid)
        if previous is None:
            self.records[modid] = item
            self.sources[modid] = source
        elif previous["version"] and item["version"] and previous["version"] != item["version"]:
            self.warning(f"{modid} 有多个版本：保留 {previous['version']} "
                         f"({self.sources[modid]})，跳过 {item['version']} ({source})")
        else:
            for key in ("name", "version"):
                if not previous[key] or (key == "name" and previous[key] == modid):
                    previous[key] = item[key] or previous[key]

    def scan(self, folder):
        folder = Path(folder).expanduser()
        if not folder.is_dir():
            raise ValueError(f"文件夹路径无效：{folder}")
        # Real files precede nested dependencies, so an explicitly installed mod wins.
        files = []
        for root, directories, filenames in os.walk(folder, followlinks=False,
                                                     onerror=lambda e: self.warning(str(e))):
            directories.sort(key=lambda value: (value.casefold(), value))
            for name in sorted(filenames, key=lambda value: (value.casefold(), value)):
                path = Path(root, name)
                if path.suffix.lower() in ARCHIVE_SUFFIXES:
                    files.append(path)
        for path in files:
            self.scan_file(path, nested=False)
        if self.include_nested:
            for path in files:
                self.scan_file(path, nested=True)
        return sorted(self.records.values(), key=lambda item: (item["modid"].casefold(), item["modid"]))

    def scan_file(self, path, nested):
        try:
            with zipfile.ZipFile(path) as archive:
                self.scan_archive(archive, str(path), nested=nested)
        except READ_ERRORS as error:
            # A bad top-level file is reported once, during the first pass.
            if not nested:
                self.warning(f"{path}：{error}")

    def descriptor(self, archive, name):
        raw = read_entry(archive, name)
        if name.endswith(".toml"):
            return tomllib.loads(raw.decode("utf-8-sig"))
        return load_json(raw)

    def metadata(self, archive, names, manifest, source, report):
        """Prefer current loader metadata over legacy/compatibility descriptors."""
        for filename in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml",
                         "quilt.mod.json", "fabric.mod.json", "riftmod.json",
                         "litemod.json", "mcmod.info"):
            if filename not in names:
                continue
            try:
                data = self.descriptor(archive, filename)
                nested = []
                properties = {}
                if filename == "mcmod.info":
                    items = legacy_records(data)
                elif not isinstance(data, dict):
                    raise ValueError("元数据根节点应为对象")
                elif filename.endswith(".toml"):
                    mods = data.get("mods", [])
                    if not isinstance(mods, list):
                        raise ValueError("mods 应为列表")
                    properties = data.get("properties", {})
                    if not isinstance(properties, dict):
                        properties = {}
                    items = [record(m.get("modId"), m.get("displayName"), m.get("version"))
                             for m in mods if isinstance(m, dict)]
                elif filename == "quilt.mod.json":
                    loader = data.get("quilt_loader", {})
                    details = loader.get("metadata", {})
                    items = [record(loader.get("id"), details.get("name"), loader.get("version"))]
                    nested = loader.get("jars", [])
                elif filename == "litemod.json":
                    items = [record(data.get("name"), data.get("displayName"), data.get("version"))]
                else:
                    items = [record(data.get("id"), data.get("name"), data.get("version"))]
                    nested = data.get("jars", [])
                items = [item for item in items if item["modid"]]
                if not items:
                    raise ValueError("没有有效的 modid")
                substitutions = {f"file.{key}": text_value(value)
                                 for key, value in properties.items()}
                substitutions["file.jarVersion"] = manifest.get("implementation-version", "")
                for item in items:
                    for field in ("name", "version"):
                        item[field] = re.sub(r"\$\{([^}]+)\}",
                                             lambda m: substitutions.get(m[1]) or m[0], item[field])
                        if report and "${" in item[field]:
                            self.warning(f"{source}：{item['modid']} 的 {field} 含未解析占位符 {item[field]}")
                return items, nested, filename
            except (AttributeError, TypeError, *READ_ERRORS) as error:
                if report:
                    self.warning(f"{source}!/{filename}：{error}")
        return [], [], ""

    def scan_archive(self, archive, source, nested=False, depth=0, report_unknown=True):
        names = set(archive.namelist())
        manifest = {}
        if "META-INF/MANIFEST.MF" in names:
            try:
                manifest = read_manifest(read_entry(archive, "META-INF/MANIFEST.MF"))
            except READ_ERRORS as error:
                if not nested:
                    self.warning(f"{source}!/META-INF/MANIFEST.MF：{error}")
        items, children, kind = self.metadata(archive, names, manifest, source, not nested)
        if not nested:
            self.archive_count += 1
            if not kind or kind == "mcmod.info":
                items = self.legacy_classes(archive, names, items, source)
            if not items:
                items = self.special_metadata(archive, names, manifest, source)
            if not items and report_unknown:
                self.warning(f"{source}：未识别到模组元数据，已跳过")
            for item in items:
                if not item["version"]:
                    self.warning(f"{source}：{item['modid']} 缺少可静态读取的版本信息")
                self.add(item, source)
        if nested:
            self.scan_children(archive, names, manifest, children, source, depth)

    def scan_children(self, archive, names, manifest, children, source, depth):
        paths = []
        if isinstance(children, list):
            for child in children:
                path = child.get("file") if isinstance(child, dict) else child
                if isinstance(path, str):
                    paths.append(path)
        jarjar = "META-INF/jarjar/metadata.json"
        if jarjar in names:
            try:
                metadata = self.descriptor(archive, jarjar)
                paths.extend(item["path"] for item in metadata.get("jars", [])
                             if isinstance(item, dict) and isinstance(item.get("path"), str))
            except (AttributeError, TypeError, *READ_ERRORS) as error:
                self.warning(f"{source}!/{jarjar}：{error}")
        # Forge 1.12's ContainedDeps names refer to entries under META-INF/libraries.
        for name in manifest.get("containeddeps", "").split():
            paths.append(f"META-INF/libraries/{name}")
        if not paths:
            return
        if depth >= MAX_NESTED_DEPTH:
            self.warning(f"{source}：内嵌模组超过 {MAX_NESTED_DEPTH} 层，已跳过")
            return
        for path in dict.fromkeys(paths):
            try:
                size = archive.getinfo(path).file_size
                if self.nested_bytes + size > MAX_NESTED_TOTAL or self.nested_count >= 4096:
                    raise ValueError("内嵌文件总量超过读取上限")
                raw = read_entry(archive, path, MAX_NESTED_SIZE)
                self.nested_bytes += len(raw)
                self.nested_count += 1
                with zipfile.ZipFile(io.BytesIO(raw)) as child:
                    child_source = f"{source}!/{path}"
                    # A declared dependency may be an annotation-only Forge mod.
                    # Ordinary bundled Java libraries yield no records.
                    self.scan_archive(child, child_source, depth=depth + 1, report_unknown=False)
                    self.scan_archive(child, child_source, nested=True, depth=depth + 1)
            except READ_ERRORS as error:
                self.warning(f"{source}!/{path}：{error}")

    def legacy_classes(self, archive, names, items, source):
        by_id = {item["modid"]: item for item in items}
        annotated_mods = {}
        versions = {}
        if "version.properties" in names:
            try:
                versions = read_version_properties(read_entry(archive, "version.properties"))
            except READ_ERRORS as error:
                self.warning(f"{source}!/version.properties：{error}")
        for name in sorted(names):
            if not name.endswith(".class") or name.startswith("META-INF/"):
                continue
            try:
                raw = read_entry(archive, name, MAX_CLASS_SIZE)
                if not any(marker in raw for marker in
                           (b"cpw/mods/fml/common/Mod;", b"net/minecraftforge/fml/common/Mod;")):
                    continue
                parsed = parse_class(raw)
                for annotation in MOD_ANNOTATIONS:
                    attributes = parsed["annotations"].get(annotation)
                    if attributes is None:
                        continue
                    modid = text_value(attributes.get("modid"))
                    if not modid:
                        continue
                    annotated = record(modid, attributes.get("name"), attributes.get("version"))
                    previous = by_id.get(modid, record(modid))
                    # Match FMLModContainer's getName/getVersion. useMetadata
                    # controls dependency information, not this version precedence.
                    annotated_mods[modid] = record(
                        modid, previous["name"] or annotated["name"] or modid,
                        annotated["version"] or versions.get(f"{modid}.version")
                        or previous["version"] or "1.0")
            except READ_ERRORS as error:
                self.warning(f"{source}!/{name}：{error}")
        # mcmod.info may also describe unused compatibility modules. If actual
        # @Mod declarations exist, only those identify mods in this archive.
        return list((annotated_mods or by_id).values())

    def special_metadata(self, archive, names, manifest, source):
        if "guichaguri/betterfps/BetterFps.class" in names:
            return [record("betterfps", manifest.get("tweakname", "BetterFps"),
                           manifest.get("tweakversion", ""))]
        if any(name.startswith("optifine/") for name in names):
            for name in ("net/optifine/Config.class", "Config.class", "optifine/Config.class"):
                if name in names:
                    try:
                        constants = parse_class(read_entry(archive, name, MAX_CLASS_SIZE))["constants"]
                        version = text_value(constants.get("VERSION"))
                        if not version:
                            version = "_".join(text_value(constants.get(key)) for key in
                                               ("MC_VERSION", "OF_EDITION", "OF_RELEASE")
                                               if text_value(constants.get(key)))
                        return [record("OptiFine", "OptiFine", version)]
                    except READ_ERRORS as error:
                        self.warning(f"{source}!/{name}：{error}")
        # Arbitrary Java getters are never executed; read only literal return values.
        items = []
        for name in sorted(names):
            basename = name.rsplit("/", 1)[-1]
            if not name.endswith(".class") or "$" in basename:
                continue
            if not (basename.startswith("mod_") or basename.startswith("LiteMod")):
                continue
            try:
                parsed = parse_class(read_entry(archive, name, MAX_CLASS_SIZE))
                methods = parsed["methods"]
                if basename.startswith("mod_") and (parsed["super"] or "").rsplit("/", 1)[-1] in ("BaseMod", "BaseModMp"):
                    modid = basename[:-6]
                    items.append(record(modid, methods.get("getName") or modid,
                                        methods.get("getVersion") or methods.get("Version")))
                elif "com/mumfrey/liteloader/LiteMod" in parsed["interfaces"]:
                    modid = basename[7:-6].lower()
                    items.append(record(modid, methods.get("getName"), methods.get("getVersion")))
            except READ_ERRORS as error:
                self.warning(f"{source}!/{name}：{error}")
        return items


def export_mods(folder, *, include_nested=True, ignored=(), compact=False):
    scanner = ModScanner(include_nested=include_nested, ignored=ignored)
    records = scanner.scan(folder)
    # Relative to the invoking shell's cwd, never to __file__ or the mods path.
    destination = Path.cwd() / OUTPUT_NAME
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix=".lme_export-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(records, stream, ensure_ascii=False, indent=None if compact else 4,
                      separators=(",", ":") if compact else None)
            stream.write("\n")
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return destination, len(records), scanner.warning_count


def get_path():
    while True:
        path = input("请输入模组文件夹路径：").strip().strip('"')
        if Path(path).expanduser().is_dir() and path:
            return path
        print("文件夹路径无效，请重试。")


def main(argv=None):
    parser = argparse.ArgumentParser(description="扫描 Minecraft 模组目录，在当前工作目录生成 lme_export.json")
    parser.add_argument("folder", nargs="?", help="模组文件夹路径；省略时交互输入")
    parser.add_argument("--no-nested", action="store_true", help="只列出外层模组，省略内嵌依赖")
    parser.add_argument("--ignore", action="append", default=[], metavar="MODID", help="忽略指定 modid，可重复")
    parser.add_argument("--compact", action="store_true", help="输出紧凑 JSON")
    args = parser.parse_args(argv)
    try:
        folder = args.folder or get_path()
        destination, count, warnings = export_mods(folder, include_nested=not args.no_nested,
                                                   ignored=args.ignore, compact=args.compact)
    except (OSError, ValueError) as error:
        print(f"导出失败：{error}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\n已取消导出。", file=sys.stderr)
        return 1
    print(f"已导出 {count} 个模组至 {destination}（{warnings} 条警告）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
