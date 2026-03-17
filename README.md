# RenderDoc-Python-Test

基于 Python + RenderDoc 的自动化工具仓库，当前主要覆盖两类能力：

- 远程启动与截帧（Android / ADB）
- `.rdc` 解析与结构化落盘（Material / Texture / Shader / Pass）

当前解析契约版本：`schema_version=1.5.0`

## 1. 项目特性

- 支持单文件任务 `rdc_parse`
- 支持批量任务 `rdc_parse_batch`
- 统一入口文件 `rdc_entry.json`
- Material / Texture / Shader / Pass 四类实体独立落盘
- 纹理 PNG 按内容去重
- Shader 源码按内容去重
- `pkg=cos` 时可自动打 zip 包
- 支持 `pre_task` / `post_task` 简单任务链

## 2. 目录结构

```text
RenderDoc-Python-Test/
├─ src/
│  ├─ main.py
│  ├─ capture/
│  ├─ common/
│  ├─ parse/
│  │  ├─ environment/
│  │  │  └─ cos_params.py
│  │  ├─ modules/
│  │  ├─ rdc_parse_pipeline.py
│  │  └─ rdc_parser.py
│  └─ task/
│     ├─ task_manager.py
│     ├─ cmd_task.py
│     ├─ parse_rdc_task.py
│     ├─ rename_rdc_task.py
│     └─ tcp_server_task.py
├─ docs/
│  ├─ rdc_parse.md
│  └─ assets/
├─ include/
├─ lib/
├─ save/
├─ output/
├─ config.ini
└─ README.md
```

## 3. 环境要求

- Python `3.10+`
- Android 场景需安装 `adb`
- 仓库自带 RenderDoc Python 绑定与相关动态库

说明：

- 推荐统一通过 `python src/main.py ...` 启动
- 启动入口会自动初始化 RenderDoc Python 运行环境

## 4. 配置文件

配置文件路径：`config.ini`

示例：

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

- `path.save_dir_abs`：默认 `.rdc` 目录；为空时使用仓库内 `save/`
- `Network.listen_host / listen_port`：TCP Server 监听地址
- `Android.package_name / activity_name`：目标 App 启动入口
- `Android.device_serial`：指定设备序列号
- `Task.default_task_id`：默认任务

## 5. 命令格式

```bash
python src/main.py <task_id> key=value key=value ...
```

通用链式参数：

- `pre_task=task_a,task_b`
- `post_task=task_a,task_b`

说明：

- 第一版仅支持任务名列表
- 子任务复用当前命令参数
- `pre_task` / `post_task` 不会继续向下传递
- 与当前任务同名的 hook 会自动跳过

## 6. 主要任务

### 6.1 控制台模式

```bash
python src/main.py
```

### 6.2 单文件解析

任务名：`rdc_parse`  
兼容别名：`parse_rdc`

```bash
python src/main.py rdc_parse rdc=save/1.rdc
```

参数：

- `rdc` / `input` / `file` / `path`：输入 `.rdc`
- `save_dir`：未指定 `rdc` 时使用该目录内最新 `.rdc`
- `output`：输出目录名
- `pkg`：打包模式
- `export_texture_assets=true|false`：是否导出纹理图片，默认 `false`
- `export_shader_assets=true|false`：是否导出 Shader 源码，默认 `true`

`output` 规则：

- 不填写：输出到 `output/`
- `output=name`：输出到 `output/<rdc文件名>/`
- `output=<其他名称>`：输出到 `output/<其他名称>/`

`pkg` 规则：

- 不填写：四类实体目录直接落在当前输出目录
- `pkg=cos`：四类实体目录打包为 `rdc_<build_num>_<tex_quality>_<timestamp>.zip`

说明：

- `pkg=cos` 时，zip 文件位于 `rdc_entry.json` 同级目录
- zip 内部第一层直接是 `rdc_material/`、`rdc_texture/`、`rdc_shader/`、`rdc_pass/`
- zip 文件名会写入 `rdc_entry.json` 的 `cos_params.package`

示例：

```bash
python src/main.py rdc_parse rdc=save/1.rdc
python src/main.py rdc_parse rdc=save/1.rdc export_texture_assets=true export_shader_assets=true
python src/main.py rdc_parse rdc=save/1.rdc output=name
python src/main.py rdc_parse rdc=save/1.rdc output=my_capture pkg=cos
```

### 6.3 批量解析

任务名：`rdc_parse_batch`

```bash
python src/main.py rdc_parse_batch dir=save
```

参数：

- `dir`：批量解析目录，默认使用 `save_dir`
- `output`：默认按 `name` 处理
- `workers`：并发子进程数，默认 `1`
- `pkg`：与 `rdc_parse` 相同
- `export_texture_assets=true|false`
- `export_shader_assets=true|false`

`output` 规则：

- 不填写：等价于 `output=name`
- `output=name`：每个 `.rdc` 输出到 `output/<rdc文件名>/`
- `output=<其他名称>`：每个 `.rdc` 输出到 `output/<其他名称>/<rdc文件名>/`

说明：

- `workers=1` 时顺序解析
- `workers>1` 时会启动多个子进程并行执行 `rdc_parse`
- 推荐先从 `workers=2` 开始测试，不建议一开始开太大

示例：

```bash
python src/main.py rdc_parse_batch dir=save
python src/main.py rdc_parse_batch dir=save pkg=cos
python src/main.py rdc_parse_batch dir=save workers=2
python src/main.py rdc_parse_batch dir=save output=my_batch
python src/main.py rdc_parse_batch dir=save pre_task=rename_rdc
```

### 6.4 批量重命名

任务名：`rename_rdc`  
兼容别名：`rdc_rename`

```bash
python src/main.py rename_rdc save_dir=save
```

功能：

- 将目录内 `.rdc` 统一重命名为 `1.rdc, 2.rdc, 3.rdc ...`

### 6.5 TCP Server

任务名：`server`

```bash
python src/main.py server
```

### 6.6 Ubuntu 20.04 Docker 打 Linux 包

如果你希望在 `ubuntu:20.04` 环境里打 Linux 包，可以直接使用：

- Windows: `tools/pkg_linux_ubuntu20_04.bat`
- Linux/macOS: `tools/pkg_linux_ubuntu20_04.sh`

对应 Dockerfile：

- `tools/docker/ubuntu20.04.Dockerfile`

说明：

- 容器内会安装 Python `3.10` 和 `PyInstaller`
- 打包逻辑复用 `tools/pkg.sh`
- 输出文件仍然写回宿主机的 `bin/rdc_tool_linux`

## 7. RDC 输出结构

单文件常见输出：

```text
output/<capture_name>/
├─ rdc_entry.json
├─ rdc_material/
├─ rdc_texture/
├─ rdc_shader/
└─ rdc_pass/
```

`pkg=cos` 输出：

```text
output/<capture_name>/
├─ rdc_entry.json
└─ rdc_<build_num>_<tex_quality>_<timestamp>.zip
```

入口文件 `rdc_entry.json` 负责提供：

- `capture_file`
- `capture_id`
- `cos_params`
- `artifacts`

完整字段说明见：

- [docs/rdc_parse.md](docs/rdc_parse.md)

流程图：

- ![RDC Parse Flow](docs/assets/rdc_parse_flow_full_v1.png)

## 8. 常见问题

### 8.1 `import renderdoc` 失败

- 确认使用 `python src/main.py ...`
- 检查 `lib/` 是否完整

### 8.2 找不到 `.rdc`

- 显式传入 `rdc=<path>`
- 或检查 `save_dir` / `config.ini`

### 8.3 图片没导出

- 检查是否设置了 `export_texture_assets=false`
- 查看对应 `rdc_texture.json` 的 `export_error`

### 8.4 材质语义字段为空

- `pass_channels`
- `material_instance_names`
- `mesh_names`

这些字段依赖 marker 质量，出现空值是允许的。

## 9. 相关文档

- [docs/rdc_parse.md](docs/rdc_parse.md)
- `docs/assets/rdc_parse_flow_overview.png`
- `src/task/`
