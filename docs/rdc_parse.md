# RDC Parse 解析框架

本文档定义当前仓库 `rdc_parse` 的生产输出契约（当前版本：`schema_version=1.5.0`）。

目标：

- 单 `.rdc` 解析
- manifest 入口驱动
- Material / Texture / Shader / Pass 四类实体落盘
- 重资产（纹理图片、shader源码）按参数开关导出
- 索引可校验（`id/path/sha256`）
- 支持批量任务 `rdc_parse_batch`

---

## 1. 固定约定

### 1.1 输出路径

默认不传 `output` 时输出固定：

- `output/rdc_entry.json`

若传入 `output=name`，则输出为：

- `output/<rdc文件名>/rdc_entry.json`

若传入 `output=<其他名称>`，则输出为：

- `output/<其他名称>/rdc_entry.json`

### 1.2 固定 schema

任务内部固定 revision-1（无需 `schema=1` 参数）。

### 1.3 固定目录名

输出目录下固定目录：

- `rdc_material/`
- `rdc_texture/`
- `rdc_shader/`
- `rdc_pass/`

---

## 2. 运行参数

单文件任务：`rdc_parse`  
批量任务：`rdc_parse_batch`

- `rdc` / `input` / `file`：输入 capture 路径
- `dir`：批量解析目录；仅 `rdc_parse_batch` 使用，默认 `save_dir`
- `output`
  - 不填写：输出目录为 `output/`
  - `output=name`：输出目录为 `output/<rdc文件名>/`
  - `output=<其他名称>`：输出目录为 `output/<其他名称>/`
- `pkg`
  - 不填写：`rdc_material/`、`rdc_texture/`、`rdc_shader/`、`rdc_pass/` 直接放在当前输出目录
  - `pkg=cos`：四类实体目录打包为 `rdc_<build_num>_<tex_quality>_<end_time_str>.zip`，zip 内部不再额外包一层同名目录
- `export_texture_assets=true/false`（默认 `true`）
  - 控制纹理图片 `image.png` 是否导出
- `export_shader_assets=true/false`（默认 `true`）
  - 控制 shader 源码文件是否导出

说明：

- shader JSON 始终导出（仅源码文件受参数控制）。
- `rdc_parse_batch` 默认按 `output=name` 处理。
- `rdc_parse_batch` 若传 `output=<其他名称>`，实际输出为 `output/<其他名称>/<rdc文件名>/`，避免多个 capture 相互覆盖。

---

## 3. 入口清单 `rdc_entry.json`

示例：

```json
{
  "schema_version": "1.5.0",
  "capture_file": "1.rdc",
  "capture_id": "cap:...",
  "cos_params": {
    "build_num": "-1",
    "platform_type": "-1",
    "tex_quality": "-1",
    "override_device": "-1",
    "package": "rdc_1234_1_20260316113045.zip"
  },
  "artifacts": {
    "materials": {
      "index": "rdc_material/rdc_material_index.json",
      "count": 296
    },
    "textures": {
      "index": "rdc_texture/rdc_texture_index.json",
      "count": 405
    },
    "shaders": {
      "index": "rdc_shader/rdc_shader_index.json",
      "count": 233
    },
    "passes": {
      "index": "rdc_pass/rdc_pass_index.json",
      "count": 362
    }
  }
}
```

字段说明：

- `schema_version`：数据契约版本
- `capture_file`：仅文件名（不含绝对路径）
- `capture_id`：由文件元信息生成的 capture 指纹
- `cos_params`：当前运行环境参数，由 `CosParams` 类统一构建；当 `pkg=cos` 时会额外包含 `package`
- `artifacts`：四类集合入口与数量统计

---

## 4. artifacts 与索引契约

每个集合结构：

```json
{
  "index": "<relative_index_path>",
  "count": 123
}
```

索引项格式（四类统一）：

```json
[
  {
    "id": "...",
    "path": "rdc_xxx/.../rdc_xxx.json",
    "sha256": "..."
  }
]
```

含义：

- `id`：集合内对比/去重键
- `path`：相对于 `rdc_entry.json` 的相对路径
- `sha256`：目标 JSON 文件哈希

索引文件：

- `rdc_material/rdc_material_index.json`
- `rdc_texture/rdc_texture_index.json`
- `rdc_shader/rdc_shader_index.json`
- `rdc_pass/rdc_pass_index.json`

---

## 5. 实体 JSON 结构

### 5.1 Material

路径：`rdc_material/<material_id>/rdc_material.json`

```json
{
  "material_base_key": "mat:...",
  "usage_count": 42,
  "material_instance_names": ["mi_xxx", "MID_mi_xxx_123456"],
  "pass_channels": ["MobileBasePass", "MobileDebugView"],
  "mesh_names": ["sm_xxx"],
  "sample_marker_paths": [
    "Frame .../MobileBasePass/mi_xxx sm_xxx (1 instances)"
  ],
  "texture_json_paths": [
    "rdc_texture/ResourceId__123/rdc_texture.json"
  ],
  "shader_json_paths": [
    "rdc_shader/md5_xxx/rdc_shader.json"
  ]
}
```

### 5.2 Texture

路径：`rdc_texture/<texture_id>/rdc_texture.json`

```json
{
  "resource_id": "ResourceId::123",
  "resource_name": "...",
  "width": 1024,
  "height": 1024,
  "mips": 11,
  "array_size": 1,
  "format": "ASTC_UNORM",
  "texture_compare_key": "texcmp:...",
  "image_path": "rdc_texture/_shared_images/img_f3b4...9a.png",
  "image_sha256": "...",
  "export_error": "..."
}
```

说明：

- `image_path` / `image_sha256` 仅在图片成功导出时存在。
- 图片文件按内容去重，多个纹理若导出 PNG 内容一致会引用同一个 `image_path`。
- 导出失败会写 `export_error`。

### 5.3 Shader

路径：`rdc_shader/<shader_id>/rdc_shader.json`

```json
{
  "shader_key": "md5:...",
  "stage": "Pixel",
  "entry_point": "main",
  "source_line_count": 892,
  "usage_count": 42,
  "source_files": [
    {
      "source_path": "rdc_shader/_shared_sources/src_a1b2c3d4e5f6a7b8.glsl"
    }
  ]
}
```

说明：

- `source_path` 仅在 `export_shader_assets=true` 时存在。
- 单个源码行数统一看顶层 `source_line_count`，`source_files` 不再重复输出 `line_count`。
- 源码文件按内容去重，多个 shader 若源码一致会引用同一个 `source_path`。

### 5.4 Pass

路径：`rdc_pass/<pass_id>/rdc_pass.json`

```json
{
  "pass_key": "pass:...",
  "pass_features": {
    "pipeline_type": "OpenGL",
    "marker_path": "Frame .../ElementBatch",
    "pass_channel": "MobileBasePass",
    "output_resource_ids": ["ResourceId::8942"],
    "depth_output_resource_id": "",
    "pipeline_object": ""
  },
  "usage_count": 8,
  "material_json_paths": [
    "rdc_material/mat_xxx/rdc_material.json"
  ],
  "material_instance_names": ["mi_xxx"],
  "mesh_names": ["sm_xxx"]
}
```

说明：

- Pass 第一版仅保留材质引用，不直接输出 Texture / Shader 引用。
- 关系可按 `Pass -> Material -> Texture/Shader` 解析。
- 适合平台按 Pass 维度做分析与对比。
- `material_instance_names`、`mesh_names`、`pass_channel` 来源于 marker 解析，依赖 capture 内标记质量。
- `pass_channel` 会做标准化；非标准标签（如含空格、`=`、`::`、括号）会置空字符串。

---

## 6. 关键对比键策略

- `shader_key`：优先源码 md5（适合跨批次对比）
- `texture_compare_key`：基于名称/格式/尺寸/mips/数组维度
- `material_base_key`：由纹理签名 + 采样器签名 + 常量布局签名组合
- `pass_key`：由 marker + 输出目标 + 深度目标 + 管线对象等信息签名

---

## 7. 上报平台建议流程

1. 读取 `rdc_entry.json`
2. 读取 `artifacts.<collection>.index`
3. 校验各 JSON 的 `sha256`
4. 入库实体 JSON
5. 按需拉取重资产（`image.png`、shader 源码文件）

推荐主键：

- Material：`material_base_key`
- Texture：`texture_compare_key`
- Shader：`shader_key`
- Pass：`pass_key`

---

## 8. 已知限制

- 部分纹理无法回读，Texture JSON 会出现 `export_error`。
- 当前 Material 为关系扁平模型，不包含深层 variant/context 结构。

---

## 9. 常用命令

全量导出：

```bash
python src/main.py rdc_parse rdc=E:/captures/1.rdc export_texture_assets=true export_shader_assets=true
```

关闭纹理图片导出：

```bash
python src/main.py rdc_parse rdc=E:/captures/1.rdc export_texture_assets=false export_shader_assets=true
```

关闭 shader 源码导出：

```bash
python src/main.py rdc_parse rdc=E:/captures/1.rdc export_texture_assets=true export_shader_assets=false
```

---

## 10. 代码模块拆分（便于扩展）

当前解析器已按实体能力拆分为独立模块：

- `src/parse/modules/texture_module.py`
  - 纹理收集、纹理导出、纹理 JSON 落盘
- `src/parse/modules/shader_module.py`
  - Shader 提取、源码落盘、Shader JSON 落盘
- `src/parse/modules/material_module.py`
  - 材质签名构建、Material JSON 落盘
- `src/parse/modules/pass_module.py`
  - Pass 特征提取、marker 解析、Pass JSON 落盘
- `src/parse/rdc_parse_pipeline.py`
  - 编排层：驱动 action 遍历、聚合关系、写入口索引

扩展建议：

- 新增实体（例如 `mesh`）时，优先新增独立模块文件；
- 在编排层仅维护关系聚合和 artifacts 索引，不在编排层堆叠实体细节逻辑；
- 保持模块输入/输出稳定（`extract_*`, `persist_*`），降低跨模块改动成本。
