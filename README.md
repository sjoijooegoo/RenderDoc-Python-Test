# RenderDoc-Python-Test

一个基于 Python + RenderDoc 的自动化工具仓库，面向 **远程启动 App、截帧、以及 `.rdc` 解析（材质/Shader 维度）** 的工作流。

> 当前仓库已经包含 RenderDoc Python 绑定与平台动态库（`include/`、`lib/`），开箱即可在对应平台使用。

---

## 功能概览

- **远程控制截帧（Android / ADB）**
  - 启动 RenderDoc 远程服务
  - 启动目标 App 并注入
  - 触发截帧并保存到本地目录

- **RDC 解析（核心）**
  - 解析单个 `.rdc` 文件
  - 提取材质与 Shader 信息
  - 输出结构化 JSON 报告（默认：`output/rdc_material_shader.json`）

- **辅助任务**
  - `.rdc` 文件按数值后缀自动重命名：`1.rdc / 2.rdc / ...`
  - TCP Server 模式，支持外部进程下发指令控制截帧流程

---

## 目录结构

```text
RenderDoc-Python-Test/
├─ src/
│  ├─ main.py                     # 程序入口
│  ├─ capture/remote_object.py    # RenderDoc 远程连接与截帧
│  ├─ parse/material_shader_parser.py # rdc 解析核心
│  ├─ task/
│  │  ├─ cmd_task.py              # 交互式控制台任务
│  │  ├─ parse_rdc_task.py        # rdc_parse / parse_rdc
│  │  ├─ rename_rdc_task.py       # rename_rdc / rdc_rename
│  │  └─ tcp_server_task.py       # server
│  └─ common/global_config.py     # 配置加载与运行环境初始化
├─ config.ini                     # 运行配置
├─ include/renderdoc/             # RenderDoc Python API 包
├─ lib/                           # 平台动态库（已接入 LFS）
├─ bin/                           # 工具二进制（已接入 LFS）
├─ docs/rdc_parse.md              # RDC 解析方案文档
└─ tools/                         # 打包脚本
```

---

## 环境要求

- Python 3.10
- Git（若拉取含 LFS 文件，需安装 Git LFS）
- ADB（如需 Android 远程截帧）

如仓库内大文件用到 LFS，请先执行：

```bash
git lfs install
git lfs pull
```

---

## 配置说明（`config.ini`）

```ini
[path]
save_dir_abs =

[Network]
listen_port = 16688
listen_host = 127.0.0.1

[Android]
package_name = com.tencent.mho
activity_name = com.epicgames.unreal.SplashActivity
device_serial =

[Task]
default_task_id = cmd
default_task_params =
```

关键项：

- `path.save_dir_abs`：本地截帧保存目录；为空时默认 `项目根/save`
- `Android.package_name/activity_name`：目标 App 启动入口
- `Android.device_serial`：指定设备序列号（不填则默认首个设备）
- `Task.default_task_id`：默认任务（无命令行参数时使用）

---

## 快速开始

### 1) 交互式控制台（默认）

```bash
python src/main.py
```

控制台可用命令：

- `rdc`：启动 RenderDoc 远程服务
- `app`：启动目标 App
- `cap [name]`：截帧（可选文件名）
- `exit`：退出

### 2) 解析 `.rdc` 输出 JSON

```bash
python src/main.py rdc_parse rdc=E:/path/to/xxx.rdc output=output/rdc_material_shader.json include_source=false
```

参数说明：

- `rdc` / `input` / `file`：输入 `.rdc` 路径
- `output` / `out`：输出 JSON 路径
- `include_source`：是否输出 shader 源码内容（`true/false`）

若不提供 `rdc`，会尝试从 `save_dir` 中选最新 `.rdc`。

兼容任务名：`parse_rdc`

### 3) 批量重命名 `.rdc`

```bash
python src/main.py rename_rdc save_dir=E:/captures
```

会按文件名中的数值后缀排序后重命名为 `1.rdc, 2.rdc...`。

兼容任务名：`rdc_rename`

### 4) TCP 服务模式

```bash
python src/main.py server
```

默认监听 `127.0.0.1:16688`，支持 JSON 指令（见 `src/common/command_type.py`）：

- `0` Launch_RDC
- `1` Launch_APP
- `2` APP_CAPTURE
- `3` CLOSE_CONNNET
- `4` SET_DIR
- `5` SET_DEVICE_SERIAL

---

## RDC 解析输出

完整文档见：`docs/rdc_parse.md`

---

## 常见问题

### 1. 提示找不到 renderdoc 模块
- 确保通过 `python src/main.py ...` 启动，让 `common.cfg.setup_python_env()` 生效。
- 检查 `lib/<platform>` 路径是否完整。

### 2. Android 设备未连接
- 执行 `adb devices` 确认在线。
- 如多设备，配置 `Android.device_serial`。

### 3. `.rdc` 解析失败
- 先确认文件有效且后缀为 `.rdc`。
- 某些 capture 的调试信息可能不完整，导致源码字段为空，这是正常情况。

---

## 后续建议

- 增加 `requirements.txt` 与一键启动脚本
- 在 README 中补充 TCP 指令请求/响应示例
- 为 `rdc_parse` 增加多版本对比命令入口（结合 `docs/rdc_parse.md` 6.x 方案）
