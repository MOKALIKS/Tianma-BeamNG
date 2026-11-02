# Tianma BeamNG · V1.0

上海天马赛车场的 BeamNG.drive 地图转换项目，基于 SkytenZ 制作的 Assetto Corsa 地图。转换与整理：MOKALIKS。

本仓库包含转换源码、打包/安装工具和说明文档。可安装的地图 ZIP 通过 [GitHub Releases](https://github.com/MOKALIKS/Tianma-BeamNG/releases) 单独提供；仓库源码压缩包不能直接作为游戏模组使用。

## 功能

- 赛道、维修区、建筑与护栏，三个自由驾驶出生点。
- 柏油材质、半透明轮胎印、红白路肩、带距离 LOD 的立体植被。
- 基础颜色 sRGB、地图曝光补偿，以及细铁丝网闪烁处理。
- 主赛道与维修区道路导航，共 306 个节点，用于地图道路显示。
- 维修区中段接取全赛道计时赛；起终点位于赛道计时线。
- 静止/飞驰起步，可选 1–20 圈，默认 3 圈；17 个中途检查点加起终点。

星级按完成比赛后的最佳单圈评定，时间恰好等于门槛也计入：

| 星级 | 单圈时间 |
| --- | --- |
| ★ | ≤ 1:20.000 |
| ★★ | ≤ 1:10.000 |
| ★★★ | ≤ 1:05.000 |

## 安装与游玩

1. 退出 BeamNG.drive。
2. 下载 Release 附件 `st_stctk_ac_port.zip`，保持压缩状态，放入游戏用户目录的 `mods` 或 `mods/repo`。移除其他位置的同地图旧副本。
3. 手动启动游戏，选择 **Shanghai Tianma Circuit v1.0**。
4. 前往维修区中段，接取 **上海天马山 · 全赛道计时赛 / Tianma Full Circuit**。

默认用户模组路径：`%LOCALAPPDATA%\BeamNG\BeamNG.drive\current\mods\repo`。如果使用自定义用户目录，以启动器显示的位置为准。

## 从源码构建

需要 Windows、Python 3.13、原始未加密的 `st_stctk` 地图以及本地 BeamNG.drive 安装。源地图和游戏资产不包含在本仓库中。工具针对这张赛道编写，不是通用 AC 地图一键转换器。

在仓库目录执行 PowerShell 命令，将路径换成自己的路径：

```powershell
.\Build.ps1 -TrackRoot 'F:\st_stctk' -GameRoot 'E:\SteamLibrary\steamapps\common\BeamNG.drive' -InstallDependencies
```

产物为 `<TrackRoot>\_beamng_conversion\output\st_stctk_ac_port.zip`。脚本运行离线检查，不启动或安装游戏。随后可选择：

```powershell
.\Install-Mod.ps1 -TrackRoot 'F:\st_stctk'
```

详见 [构建说明](docs/BUILD.md)、[验证与已知限制](docs/TESTING.md) 和 [V1.0 发布说明](releases/v1.0/RELEASE_NOTES.md)。

## 验证状态与来源

地图此前已经由用户在游戏内加载和驾驶；最终起步方向修订按用户反馈旋转了 180°。最终包通过模型、贴图、ZIP、原生 Lua 路网/计时赛/评分边界等离线检查，最终朝向和全部视觉效果仍需游戏内复测。

原地图、游戏模型与贴图分别属于各自权利人；本项目不是 BeamNG 或原地图作者的官方作品。署名和资源说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
