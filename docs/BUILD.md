# 构建说明

## 环境与输入

已使用 Windows x64 / Python 3.13 构建。依赖版本记录在 `requirements.txt`。Python 需要可用的 pip；离线环境可自行安装同版本依赖。

原地图目录需要包含：

```text
st_stctk/
  models.ini
  st_stctk.kn5
  st_builds.kn5
  st_stcgrooverad.kn5
  st_walls.kn5
  st_trees.kn5
  st_horizontal.kn5
  st_misc1.kn5
  st_misc2.kn5
  ai/fast_lane.ai
  ai/pit_lane.ai
  ui/preview.png
```

本地 BeamNG 安装需包含 `content/levels/hirochi_raceway.zip`、`content/assets/materials/tree.zip`、`lua/common/mathlib.lua` 与原生 `gameplay/missionTypes/timeTrial`。游戏资源结构或 Lua 接口变化可能需要适配。

## 构建流程

```powershell
.\Build.ps1 -TrackRoot 'F:\st_stctk' -GameRoot 'E:\SteamLibrary\steamapps\common\BeamNG.drive' -Python 'C:\Python313\python.exe' -InstallDependencies
```

`-Python` 默认为 PATH 中的 `python`。首次使用 `-InstallDependencies` 将依赖安装进源地图的 `_beamng_conversion/tools/lib`；依赖已存在时可以省略该参数。

脚本把本仓库的工具同步到 `<TrackRoot>/_beamng_conversion/tools`，会更新该目录中的同名工具文件。原始 KN5 保留不变。构建产物、检查报告、依赖和临时文件均放在 `<TrackRoot>/_beamng_conversion` 下。

`-GameRoot` 会设置当前构建进程的 `BEAMNG_GAME_ROOT`，结束后恢复环境变量。手动调用转换器时也需设置此变量，以定位本地植被资源。

输出：

| 文件 | 用途 |
| --- | --- |
| `output/st_stctk_ac_port.zip` | 可安装地图 |
| `output/SHA256.txt` | 当前构建校验值 |
| `output/unpacked/` | 关卡与计时赛目录 |
| `output/offline_validation.json` | 模型、材质和 ZIP 检查 |
| `output/v1_validation.json` | 原生 Lua 任务、导航、评分与旋转检查 |
| `output/time_trial_route.png` | 计时赛路线图 |
| `work/conversion_report.json` | 转换清单与限制 |

ZIP 保留文件时间用于游戏缓存失效，因此重新构建的 ZIP 哈希不保证与已发布附件一致；使用同一构建生成的校验文件验证它。

## 安装

```powershell
.\Install-Mod.ps1 -TrackRoot 'F:\st_stctk'
# 自定义用户目录：
.\Install-Mod.ps1 -TrackRoot 'F:\st_stctk' -ModsDirectory 'D:\BeamNGUser\mods\repo'
```

安装器要求游戏已退出，校验当前 ZIP 与验证报告的 SHA-256，备份旧包后原子替换。只清除本地图的旧模组登记，不启动或结束游戏进程。

## 工具结构

- `kn5_reader.py` / `convert_track.py`：读取 KN5、坐标/UV 转换、场景与材质生成。
- `texture_compat.py` / `visual_revision.py`：DDS、sRGB、路肩、柏油、轮胎印和植被处理。
- `time_trial.py`：任务、星级、路线检查点、导航节点和起步朝向。
- `map_exposure.lua`：地图曝光补偿与退出恢复。
- `package_mod.py` / `install_fixed_mod.py`：经典 ZIP、完整性校验、备份与安装。
- `validate_*.py` / `validation_images.py`：离线验证，部分检查读取本地游戏 Lua。
- `audit_track.py` / `audit_wheel_contacts.py`：重复面、轮迹碰撞与路面接缝诊断。

这些工具依赖源地图的具体材质名、模型名和标记布局。不要将其兼容范围理解为所有 AC 地图。
