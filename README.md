# CuteDesktopPet 🐾

这是一个基于 Python 和 PyQt6 开发的虚拟桌面陪伴宠物（Cute Desktop Pet）应用。

## 🌟 项目特性 (Features)

- **桌面悬浮陪伴**：无边框置顶窗口，可拖拽放置在屏幕任意位置，支持系统托盘管理。
- **温馨气泡对话**：内置丰富对话，定时提醒休息、喝水、加油打气等。
- **饱食度与互动喂食**：包含饱食度消耗机制，提供糖果、汉堡、蛋糕等多样化食物交互。
- **多状态帧动画**：支持待机（Idle）、奔跑（Run）、跳跃（Jump）、舞蹈（Dance）等多套动作切换。
- **资源预处理工具**：内置 `process_assets.py` 图像抠图与边缘去噪脚本，方便自定义宠物素材。
- **一键打包**：包含 PyInstaller 配置文件，方便打包为独立 `.exe` 可执行程序。

---

## 🚀 快速开始 (Quick Start)

### 1. 环境准备 (Requirements)

推荐使用 Python 3.9+ 环境，安装依赖：

```bash
pip install -r requirements.txt
```

### 2. 运行项目 (Run)

```bash
python pet.py
```

### 3. 素材预处理 (Process Assets)

如果添加了新的图片素材，可运行处理脚本清理背景：

```bash
python process_assets.py
```

### 4. 打包为 exe (Build)

使用 PyInstaller 进行打包：

```bash
pyinstaller CuteDesktopPet.spec
```

打包完成后，可执行文件将生成在 `dist/` 目录下。

---

## 📝 开源协议 (License)

MIT License
