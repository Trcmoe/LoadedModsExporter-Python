# LoadedModsExporter-Python

离线扫描 Minecraft Java 版模组文件夹，导出模组 ID、名称和版本的 JSON 列表。无需启动游戏、安装 Java 或联网查询。

## 灵感来源

[[LME]加载模组导出](https://www.mcmod.cn/class/2995.html)。本脚本保留原脚本的 `modid`、`name`、`version` 三个字段、JSON 数组结构和 `lme_export.json` 文件名，提供无需启动游戏的导出方式。

原脚本的 JSON 曾通过 MC 百科导入验证；本次修改保留其结构，但未重新验证网站当前的线上导入功能。

## 用法

需要 **Python 3.11 或更新版本**，只使用标准库，无需 `pip install`。下载仓库后，将 `LME_Final.py` 和 `java_metadata.py` 放在同一个目录。

保留原来的交互方式：

```console
python LME_Final.py
请输入模组文件夹路径：D:\Minecraft\.minecraft\mods
```

也可以直接传入路径；包含空格时加引号：

```console
python LME_Final.py "D:\Minecraft\My Pack\mods"
```

**输出始终保存在执行命令时的当前工作目录**，文件名为 `lme_export.json`。例如：

```console
cd D:\exports
python D:\tools\LoadedModsExporter-Python\LME_Final.py "D:\Minecraft\My Pack\mods"
```

结果是 `D:\exports\lme_export.json`。脚本不会切换工作目录。输入路径可以是绝对路径、相对于当前工作目录的路径或以 `~` 开头的用户目录路径。

每次运行重新生成列表并替换旧文件，不会把上一次的模组残留在结果中。即使目录中没有模组，也会写入 `[]`。JSON 使用 UTF-8，示例：

```json
[
    {
        "modid": "examplemod",
        "name": "Example Mod",
        "version": "1.2.3"
    }
]
```

可选参数（均可用于交互模式）：

| 参数 | 作用 |
| --- | --- |
| `--no-nested` | 只列出外层文件中的模组，省略内嵌依赖；适合需要接近旧脚本列表范围的场景 |
| `--ignore MODID` | 忽略指定 ID，可重复使用；始终忽略 LME 自身 `loadedmodsexporter` |
| `--compact` | 输出不带缩进的紧凑 JSON |
| `--help` | 查看帮助 |

## 识别范围

递归扫描目录中的 `.jar`、`.zip` 和 `.litemod` 文件（扩展名大小写不敏感）。跳过配置文件、`.jar.disabled` 等禁用文件，不跟随目录符号链接。

| 类型 | 读取方式 |
| --- | --- |
| Forge / NeoForge | `META-INF/mods.toml`、`META-INF/neoforge.mods.toml` 中的全部 `[[mods]]`，支持 manifest 中的版本和 `${file.<属性>}` 替换 |
| 旧版 Forge / FML | `mcmod.info` 的列表、单对象和 `modlist` 格式；静态读取旧版 `@Mod` 注解及 `version.properties` |
| Fabric / Quilt | `fabric.mod.json`、`quilt.mod.json`；支持同包兼容描述文件的优先级处理 |
| Rift | `riftmod.json` |
| LiteLoader | `litemod.json`，兼容 `mcmod.info` 和可静态读取的 LiteMod 类 |
| OptiFine / BetterFps | 从已知类常量和 manifest 读取，不依赖文件名 |
| 早期 ModLoader | 识别直接继承 `BaseMod` / `BaseModMp` 的 `mod_*` 类，读取直接返回常量的版本方法 |

默认包括加载器明确声明的内嵌模组：Fabric / Quilt 的 `jars`、Forge / NeoForge 的 JarJar `metadata.json`，以及旧 Forge manifest 的 `ContainedDeps`。不会把压缩包中未声明的任意 JAR 或只有普通 Java 类库内容的依赖列为模组，也不会把 `provides` 别名当成独立模组。

同一个文件存在多种描述文件时，使用第一个成功解析的有效描述文件，优先级为 NeoForge → Forge → Quilt → Fabric → Rift → LiteLoader → `mcmod.info`。旧 Forge 存在 `@Mod` 注解时，使用注解中的实际 ID，并按 FML 的规则合并匹配的名称和版本信息，避免把描述文件中的未使用条目也导出。

按 ID 去重并排序。版本冲突时保留先读取的版本并报告双方来源：外层文件优先于内嵌依赖，文件和子目录按名称稳定排序。**这不是加载器的依赖求解或最高版本选择**。

## 与游戏内导出的区别

LME 导出的是游戏实际加载的模组，本脚本导出的是目录中能够静态识别的模组清单。只提供 mods 路径、且不运行游戏，无法保证对所有历史版本和任意自定义模组做到与运行时完全一致：

- 不判断客户端/服务端、MC 版本、依赖是否满足，也不模拟加载器对多个候选版本的选择。
- 不添加目录之外的 Minecraft、加载器本体或启动器注入的虚拟模组。
- 不执行模组的 Java 代码。运行时计算的 ID、显示名、版本，以及缺少标准元数据的自定义 coremod，可能无法完整读取。
- 无法解析的占位符保留原值并报告；缺少可读取的版本时使用空字符串并报告。旧 Forge 注解模组没有任何版本来源时，按 FML 默认规则使用 `1.0`。

损坏的包、无效的元数据、未识别文件和冲突会输出到标准错误，正常文件继续扫描；导出完成后显示条目数和警告数。有警告时应查看对应文件，不能把结果理解为游戏已成功加载这些模组。无效的目录路径或写入失败会返回非零退出码。

读取压缩包时不解压到磁盘；元数据限制 4 MiB、单个类文件 16 MiB、单个内嵌文件 128 MiB、内嵌总量 512 MiB / 4096 个，最多 8 层。超限会报告并跳过相应部分。

## 开发验证

```console
python -m unittest discover -s tests -v
```

测试使用临时构造的模组包，覆盖各描述格式、多个模组、内嵌依赖、旧版注解、特殊模组、损坏输入、重复导出以及从不同工作目录启动。不需要下载模组或安装测试框架。

格式参考：[Fabric 元数据](https://docs.fabricmc.net/develop/loader/fabric-mod-json)、[Quilt 规范](https://github.com/QuiltMC/rfcs/blob/main/specification/0002-quilt.mod.json.md)、[Forge 模组文件](https://docs.minecraftforge.net/en/latest/gettingstarted/modfiles/)、[NeoForge 模组文件](https://docs.neoforged.net/docs/gettingstarted/modfiles/)、[旧版 FML 元数据处理](https://github.com/MinecraftForge/FML/blob/1.7.10/src/main/java/cpw/mods/fml/common/FMLModContainer.java)、[旧 Forge 内嵌依赖](https://docs.minecraftforge.net/en/1.13.x/gettingstarted/dependencymanagement/)。
