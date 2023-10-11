import os
import json
import glob
import time


def folderDetect():  # 判断文件夹名
    current_dir = os.getcwd()
    print(f"当前目录：{current_dir}")
    if os.path.basename(current_dir) != "mods":
        print("错误：该程序只能在“mods”文件夹下执行，请将程序移动至对应文件夹后重试。")
        quit()


def exportJars():
    mod_list = []
    mod_files = glob.glob("*.jar")
    # 遍历所有jar包，提取数据
    for mod_file in mod_files:
        os.system(f"jar xf {mod_file} fabric.mod.json")
        mod_json_path = "fabric.mod.json"
        # 让我看看你的json
        with open(mod_json_path, "r") as file:
            mod_json = json.load(file)
        # 提取需要的数据
        modid = mod_json["id"]
        version = mod_json["version"]
        name = mod_json["name"]
        # 构造并存储数据
        mod_data = {
            "modid": modid,
            "name": name,
            "version": version
        }
        mod_list.append(mod_data)
        os.remove(mod_json_path)
        with open("lme_export_unformat.json", "w") as output:
            json.dump(mod_list, output)


def formatJSON():
    with open("lme_export_unformat.json", "r") as file:
        data = json.load(file)
    with open("lme_export.json", "w") as file:
        json.dump(data, file, indent=4)
    os.remove("lme_export_unformat.json")


def main():
    folderDetect()
    print("正在输出，请不要关闭本窗口。")
    exportJars()
    formatJSON()
    print("输出完毕，现在可关闭本窗口。")
    time.sleep(10)

main()
