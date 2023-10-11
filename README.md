# LoadedModsExporter-Python

输出mods文件夹内所有模组的信息并以JSON的形式储存。

## 灵感来源

[[LME]加载模组导出](https://www.mcmod.cn/class/2995.html)，由于模组不常更新，因此使用Python写了一个具有相同功能的程序。在模组标准不变动的前提下，该程序能保持兼容。

输出的JSON文件经测试可以导入进mcmod且能正常读取，与原版相比，列表中不会多出一些未添加的模组（推测是原版LME将模组包含的库和前置也一并输出，导致网站读取错误）。

## 用法

需要使用Python 3（本人使用3.11进行开发，不确定在其他版本能否运行）。
将程序放置在`mods`文件夹下，程序会自动寻找`.jar`文件并读取其中存储模组信息的文件并汇总输出。

Fabric版本
~~~
Python LME_for_Fabric.py
~~~

Forge版本

~~~
Python LME_for_Forge.py
~~~
