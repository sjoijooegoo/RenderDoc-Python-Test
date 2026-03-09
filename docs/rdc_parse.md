# RDC Parse 解析框架（中文完整版）

本文档定义当前仓库 `rdc_parse` 的生产输出契约（当前版本：`schema_version=1.4.0`）。

目标：

- 单 `.rdc` 解析
- manifest 入口驱动
- Material / MaterialInstance / Texture / Shader / Pass 五类实体落盘
- 重资产（纹理图片、shader源码）按参数开关导出
- 索引可校验（`id/path/sha256`）

---

## 1. 固定约定

### 1.1 输出路径

输入 `xxx.rdc` 时输出固定：

- `output/xxx/rdc_entry.json`

其中 `xxx` 为 `.rdc` 文件名（去后缀）并做安全化处理。

### 1.2 固定 schema

任务内部固定 revision-1（无需 `schema=1` 参数）。

### 1.3 固定目录名

`output/xxx/` 下固定目录：

- `rdc_material/`
- `rdc_material_instance/`
- `rdc_texture/`
- `rdc_shader/`
- `rdc_pass/`

---

## 2. 运行参数

- `rdc` / `input` / `file`：输入 capture 路径
- `export_texture_assets=true/false`（默认 `true`）
  - 控制纹理图片 `image.png` 是否导出
- `export_shader_assets=true/false`（默认 `true`）
  - 控制 shader 源码文件是否导出

说明：

- shader JSON 始终导出（仅源码文件受参数控制）。
- `include_context_events` 当前不进入 artifacts 输出模型。

---

## 3. 入口清单 `rdc_entry.json`

示例：

```json
{
  "schema_version": "1.4.0",
  "parser_version": "rdc_parse_v1.4.0",
  "generated_at": "2026-03-09T12:34:56.123456+00:00",
  "capture_file": "1.rdc",
  "capture_id": "cap:...",
  "summary": {
    "material_count": 296,
    "material_instance_count": 494,
    "texture_count": 405,
    "shader_count": 233,
    "pass_count": 362,
    "texture_export_error_count": 12
  },
  "artifacts": {
    "materials": {
      "index": "rdc_material/rdc_material_index.json",
      "count": 296
    },
    "material_instances": {
      "index": "rdc_material_instance/rdc_material_instance_index.json",
      "count": 494
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
- `parser_version`：解析器实现版本
- `generated_at`：UTC 生成时间
- `capture_file`：仅文件名（不含绝对路径）
- `capture_id`：由文件元信息生成的 capture 指纹
- `summary`：快速统计
- `artifacts`：五类集合入口

---

## 4. artifacts 与索引契约

每个集合结构：

```json
{
  "index": "<relative_index_path>",
  "count": 123
}
```

索引项格式（五类统一）：

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
- `rdc_material_instance/rdc_material_instance_index.json`
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

### 5.2 MaterialInstance

路径：`rdc_material_instance/<material_instance_id>/rdc_material_instance.json`

```json
{
  "material_instance_key": "matinst:...",
  "material_instance_name": "mi_xxx",
  "mesh_name": "sm_xxx",
  "usage_count": 8,
  "pass_channels": ["MobileBasePass"],
  "sample_marker_paths": [
    "Frame .../MobileBasePass/mi_xxx sm_xxx (1 instances)"
  ],
  "material_json_path": "rdc_material/mat_xxx/rdc_material.json"
}
```

### 5.3 Texture

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
  "image_path": "rdc_texture/ResourceId__123/image.png",
  "image_sha256": "...",
  "export_error": "..."
}
```

说明：

- `image_path` / `image_sha256` 仅在图片成功导出时存在。
- 导出失败会写 `export_error`。

### 5.4 Shader

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
      "filename": "main.glsl",
      "line_count": 892,
      "source_path": "rdc_shader/md5_xxx/main.glsl"
    }
  ]
}
```

说明：

- `source_path` 仅在 `export_shader_assets=true` 时存在。

### 5.5 Pass

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
  "material_instance_json_paths": [
    "rdc_material_instance/matinst_xxx/rdc_material_instance.json"
  ]
}
```

说明：

- Pass 第一版仅保留材质实例引用，不直接输出 Texture / Shader 引用。
- 实体关系为：`Pass -> MaterialInstance -> Material -> Texture/Shader`。
- 适合平台按 Pass 维度做分析与对比。
- `material_instance_name`、`mesh_name`、`pass_channel` 来源于 marker 解析，依赖 capture 内标记质量。

---

## 6. 关键对比键策略

- `shader_key`：优先源码 md5（适合跨批次对比）
- `texture_compare_key`：基于名称/格式/尺寸/mips/数组维度
- `material_base_key`：由纹理签名 + 采样器签名 + 常量布局签名组合
- `material_instance_key`：由材质基底 + 实例名 + mesh 名组合签名
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
- MaterialInstance：`material_instance_key`
- Texture：`texture_compare_key`
- Shader：`shader_key`
- Pass：`pass_key`

---

## 8. 已知限制

- 部分纹理无法回读，Texture JSON 会出现 `export_error`。
- `include_context_events` 目前不在 artifacts 输出中体现。
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
