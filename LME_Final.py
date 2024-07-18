import os
import re
import json
import toml
import zipfile


def GetPath():
    while True:
        path = input("请输入文件夹路径：")
        if os.path.isdir(path):
            return path
        else:
            print("您输入的文件夹路径无效，请重试。")


def PathHandler(folder_path):
    for item in os.listdir(folder_path):  # 遍历指定的文件夹
        full_path = os.path.join(folder_path, item)
        if os.path.isdir(full_path):  # 通过递归来深入文件夹
            PathHandler(full_path)
        elif full_path.endswith('.litemod'):  # 处理使用LiteLoader的模组
            UniversalHandler(full_path)
        elif full_path.endswith('.zip'):
            UniversalHandler(full_path)
            '''
            一些旧的Forge模组会使用zip打包（比如1.6.4的ArmorStatusHUD）。
            部分这种类型的模组不包含“mcmod.info”文件（比如1.5.2的ReiMiniMap），
            很难读取到其modid等信息。
            '''
        elif full_path.endswith('.jar'):
            JarFileHandler(full_path)
        else:  # 有的模组会在存放模组的文件夹里生成配置文件或缓存，故跳过
            pass


def UniversalHandler(folder_path):
    # 用于处理LiteLoader模组以及非常早期的Forge模组(MC1.6)
    with zipfile.ZipFile(folder_path, 'r') as z:
        if 'mcmod.info' in z.namelist():
            with z.open('mcmod.info') as info_file:
                data = json.load(info_file)
                if isinstance(data, list) and len(data) > 0:
                    mod_info = data[0]
                elif isinstance(data, dict) and "modlist" in data and len(data["modlist"]) > 0:
                    mod_info = data["modlist"][0]
                else:  # 遇到了不符合预期的数据
                    return
                extracted_data = {
                    'modid': mod_info.get('modid', ''),
                    'name': mod_info.get('name', ''),
                    'version': mod_info.get('version', '')
                }
                SaveData(extracted_data)


def JarFileHandler(folder_path):
    with zipfile.ZipFile(folder_path, 'r') as z:
        if 'fabric.mod.json' in z.namelist():  # Fabric Mod
            FabricModHandler(folder_path)
        elif 'riftmod.json' in z.namelist():  # Rift Mod
            RiftModHandler(folder_path)
        elif 'quilt.mod.json' in z.namelist():  # Quilt Mod
            QuiltModHandler(folder_path)
        elif 'mcmod.info' in z.namelist(): # Legacy Forge Mod(MC1.12.2)
            LForgeModHandler(folder_path)
        elif any('META-INF/mods.toml' in file.filename for file in z.infolist()):  # Modern Forge Mod
            MForgeModHandler(folder_path)
        elif any('META-INF/neoforge.mods.toml' in file.filename for file in z.infolist()):  # NeoForge Mod
            NeoForgeModHandler(folder_path)
        else:  # 处理一些特殊的Mod
            SpecialHandler(folder_path)


def FabricModHandler(folder_path):
    with zipfile.ZipFile(folder_path, 'r') as z:
        if 'fabric.mod.json' in z.namelist():
            with z.open('fabric.mod.json') as info_file:
                data = json.load(info_file)
                extracted_data = {
                    'modid': data.get('id', ''),
                    'name': data.get('name', ''),
                    'version': data.get('version', '')
                }
                SaveData(extracted_data)


def RiftModHandler(folder_path):
    with zipfile.ZipFile(folder_path, 'r') as z:
        if 'riftmod.json' in z.namelist():
            with z.open('riftmod.json') as info_file:
                data = json.load(info_file)
                extracted_data = {
                    'modid': data.get('id', ''),
                    'name': data.get('name', ''),
                    'version': data.get('version', '')
                }
                SaveData(extracted_data)


def QuiltModHandler(folder_path):
    with zipfile.ZipFile(folder_path, 'r') as z:
        if 'quilt.mod.json' in z.namelist():
            with z.open('quilt.mod.json') as info_file:
                data = json.load(info_file)
                loader_data = data.get('quilt_loader', {})
                extracted_data = {
                    'modid': loader_data.get('id', ''),
                    'name': loader_data.get('metadata', {}).get('name', ''),
                    'version': loader_data.get('version', '')
                }
                SaveData(extracted_data)


def LForgeModHandler(folder_path):
    with zipfile.ZipFile(folder_path, 'r') as z:
        if 'mcmod.info' in z.namelist():
            with z.open('mcmod.info') as info_file:
                raw_data = info_file.read().decode('utf-8')
                cleaned_data = JSONClean(raw_data)
                if cleaned_data is None:
                    return
                if isinstance(cleaned_data, list) and len(cleaned_data) > 0:
                    mod_info = cleaned_data[0]
                elif isinstance(cleaned_data, dict):
                    mod_info = cleaned_data
                else:
                    print("mcmod.info 的数据结构不符合预期")
                    return
                extracted_data = {
                    'modid': mod_info.get('modid', ''),
                    'name': mod_info.get('name', ''),
                    'version': mod_info.get('version', '')
                }
                SaveData(extracted_data)



def MForgeModHandler(folder_path):
    with zipfile.ZipFile(folder_path, 'r') as z:
        if 'META-INF/mods.toml' in z.namelist():
            with z.open('META-INF/mods.toml') as toml_file:
                data = toml.loads(toml_file.read().decode('utf-8', errors='ignore'))
                mods = data.get('mods', [])
                if mods:
                    mod_info = mods[0]
                    version = mod_info.get('version', '')
                    # Workaround for "${file.jarVersion}" case
                    if version == '${file.jarVersion}':
                        if 'META-INF/MANIFEST.MF' in z.namelist():
                            with z.open('META-INF/MANIFEST.MF') as manifest:
                                for line in manifest:
                                    line = line.decode('utf-8').strip()
                                    if line.startswith('Implementation-Version:'):
                                        version = line.split(':', 1)[1].strip()
                                        break
                    extracted_data = {
                        'modid': mod_info.get('modId', ''),
                        'name': mod_info.get('displayName', ''),
                        'version': version
                    }
                    SaveData(extracted_data)


def NeoForgeModHandler(folder_path):
    with zipfile.ZipFile(folder_path, 'r') as z:
        if 'META-INF/neoforge.mods.toml' in z.namelist():
            with z.open('META-INF/neoforge.mods.toml') as toml_file:
                data = toml.loads(toml_file.read().decode('utf-8', errors='ignore'))
                mods = data.get('mods', [])
                if mods:
                    mod_info = mods[0]
                    extracted_data = {
                        'modid': mod_info.get('modId', ''),
                        'name': mod_info.get('displayName', ''),
                        'version': mod_info.get('version', '')
                    }
                    SaveData(extracted_data)


def SpecialHandler(folder_path):
    # TODO:处理如OptiFine、BetterFPS之类的可执行jar文件
    pass


def JSONClean(json_string):
    json_string = re.sub(r'[\x00-\x1F\x7F]', '', json_string)
    try:
        json_data = json.loads(json_string)
        formatted_data = json.dumps(json_data, indent=4)
        # print(f"Formatted JSON:\n{formatted_data}")
        return json.loads(formatted_data)
    except (TypeError, ValueError, json.JSONDecodeError) as e:
        print(f"格式化 JSON 数据时出错: {e}")
        return None


def SaveData(data, filename="lme_export.json"):
    try:
        if not data.get('modid') and not data.get('name'):  # 检查modid和name是否都为空
            return
        if os.path.isfile(filename):  # 检查文件是否存在
            with open(filename, 'r', encoding='utf-8') as file:  # 读取现有数据
                existing_data = json.load(file)
        else:
            existing_data = []
        if any(mod['modid'] == data['modid'] for mod in existing_data):  # 检查modid是否已存在
            print(f"modid: '{data['modid']}' 已存在，跳过写入。")
            return
        existing_data.append(data)  # 添加新数据
        with open(filename, 'w', encoding='utf-8') as file:  # 将更新后的数据写回文件
            json.dump(existing_data, file, indent=4)
    except Exception as e:
        print(f"发生错误：{e}")


if __name__ == "__main__":
    folder_path = GetPath()
    PathHandler(folder_path)
    print("模组信息导出已完成。")
