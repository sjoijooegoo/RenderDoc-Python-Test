# RDC Parse 解析框架

本文档描述当前 `rdc_parse` / `rdc_parse_batch` 的输出契约。

当前版本：`schema_version=1.5.0`

## 1. 目标

- 解析单个或多个 `.rdc`
- 输出统一入口 `rdc_entry.json`
- 输出四类实体：Material / Texture / Shader / Pass
- 重资产按参数控制导出
- 索引项包含 `id / path / sha256`

## 2. 任务与参数

支持的解析任务：

- `rdc_parse`
- `rdc_parse_batch`

通用参数：

- `output`
- `workers`
- `pkg`
- `export_texture_assets`
- `export_shader_assets`

单文件任务参数：

- `rdc` / `input` / `file` / `path`
- `save_dir`

批量任务参数：

- `dir`
- `save_dir`

### 2.1 output 规则

`rdc_parse`：

- 不填写：输出到 `output/`
- `output=name`：输出到 `output/<rdc文件名>/`
- `output=<其他名称>`：输出到 `output/<其他名称>/`

`rdc_parse_batch`：

- 不填写：等价于 `output=name`
- `output=name`：每个 `.rdc` 输出到 `output/<rdc文件名>/`
- `output=<其他名称>`：每个 `.rdc` 输出到 `output/<其他名称>/<rdc文件名>/`

`workers`：

- 默认 `1`
- `workers=1`：顺序解析
- `workers>1`：启动多个子进程并行执行 `rdc_parse`

说明：

- 当前实现是多进程并发，不是多线程共享同一个 RenderDoc replay 上下文
- 建议先从 `workers=2` 开始

### 2.2 pkg 规则

- 不填写：四类实体目录直接落盘
- `pkg=cos`：四类实体目录打包为 zip

zip 命名：

```text
rdc_<build_num>_<tex_quality>_<timestamp>.zip
```

说明：

- zip 与 `rdc_entry.json` 同级
- zip 内部第一层不额外包同名目录
- zip 内部第一层直接是：
  - `rdc_material/`
  - `rdc_texture/`
  - `rdc_shader/`
  - `rdc_pass/`

### 2.3 重资产导出参数

- `export_texture_assets=true|false`
  - 默认 `false`
  - 控制纹理图片是否导出
- `export_shader_assets=true|false`
  - 默认 `true`
  - 控制 Shader 源码是否导出

说明：

- Shader JSON 始终导出
- Texture JSON 始终导出

## 3. 入口文件

入口文件名固定：

```text
rdc_entry.json
```

示例：

```json
{
  "schema_version": "1.5.0",
  "capture_file": "1.rdc",
  "capture_id": "cap:...",
  "artifacts": {
    "materials": {
      "index": "rdc_material/rdc_material_index.json",
      "count": 180
    },
    "textures": {
      "index": "rdc_texture/rdc_texture_index.json",
      "count": 328
    },
    "shaders": {
      "index": "rdc_shader/rdc_shader_index.json",
      "count": 116
    },
    "passes": {
      "index": "rdc_pass/rdc_pass_index.json",
      "count": 184
    }
  },
  "cos_params": {
    "build_num": "1234",
    "tex_quality": "1",
    "map_name": "Forest_WP",
    "package": "rdc_1234_1_20260316140320.zip"
  }
}
```

字段说明：

- `schema_version`：契约版本
- `capture_file`：仅文件名
- `capture_id`：capture 指纹
- `artifacts`：四类索引入口与数量
- `cos_params`：环境参数

说明：

- `cos_params.package` 仅在 `pkg=cos` 时存在

## 4. artifacts 契约

每个集合结构：

```json
{
  "index": "<relative_index_path>",
  "count": 123
}
```

索引项格式：

```json
[
  {
    "id": "...",
    "path": "rdc_xxx/.../rdc_xxx.json",
    "sha256": "..."
  }
]
```

四类索引文件：

- `rdc_material/rdc_material_index.json`
- `rdc_texture/rdc_texture_index.json`
- `rdc_shader/rdc_shader_index.json`
- `rdc_pass/rdc_pass_index.json`

## 5. 实体结构

### 5.1 Material

路径：

```text
rdc_material/<material_id>/rdc_material.json
```

示例：

```json
{
  "material_base_key": "mat:...",
  "usage_count": 42,
  "material_instance_names": ["mi_xxx"],
  "pass_channels": ["MobileBasePass"],
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

路径：

```text
rdc_texture/<texture_id>/rdc_texture.json
```

示例：

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
  "image_path": "rdc_texture/_shared_images/img_xxx.png",
  "image_sha256": "...",
  "export_error": "..."
}
```

说明：

- `image_path` / `image_sha256` 仅在图片成功导出时存在
- 图片按内容去重，共享目录为 `rdc_texture/_shared_images/`

### 5.3 Shader

路径：

```text
rdc_shader/<shader_id>/rdc_shader.json
```

示例：

```json
{
  "shader_key": "md5:...",
  "stage": "Pixel",
  "entry_point": "main",
  "source_line_count": 892,
  "usage_count": 42,
  "source_files": [
    {
      "source_path": "rdc_shader/_shared_sources/src_xxx.glsl"
    }
  ]
}
```

说明：

- `source_path` 仅在 `export_shader_assets=true` 时存在
- Shader 源码按内容去重，共享目录为 `rdc_shader/_shared_sources/`

### 5.4 Pass

路径：

```text
rdc_pass/<pass_id>/rdc_pass.json
```

示例：

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

- Pass 第一版只直接关联 Material
- Texture / Shader 通过 `Pass -> Material` 间接关联

## 6. 对比键

- `shader_key`
- `texture_compare_key`
- `material_base_key`
- `pass_key`

这些字段适合作为平台侧去重、聚合、对比的主键或候选键。

## 7. 上报建议

建议平台读取顺序：

1. 读取 `rdc_entry.json`
2. 读取 `artifacts.<type>.index`
3. 校验各实体 JSON `sha256`
4. 入库实体 JSON
5. 按需读取图片或 Shader 源码

若使用 `pkg=cos`：

1. 读取 `rdc_entry.json`
2. 读取 `cos_params.package`
3. 打开 zip
4. 按 `artifacts.*.index` 读取 zip 内部内容

## 8. 已知限制

- 材质相关语义字段依赖 marker 质量
- 部分纹理可能无法成功导出图片
- 当前 Material 为扁平关系模型，不包含深层 variant/context

## 9. 常用命令

单文件：

```bash
python src/main.py rdc_parse rdc=save/1.rdc
python src/main.py rdc_parse rdc=save/1.rdc export_texture_assets=true export_shader_assets=true
python src/main.py rdc_parse rdc=save/1.rdc pkg=cos
```

批量：

```bash
python src/main.py rdc_parse_batch dir=save
python src/main.py rdc_parse_batch dir=save pkg=cos
python src/main.py rdc_parse_batch dir=save workers=2
python src/main.py rdc_parse_batch dir=save pre_task=rename_rdc
```

## 10. 代码模块

- `src/parse/modules/texture_module.py`
- `src/parse/modules/shader_module.py`
- `src/parse/modules/material_module.py`
- `src/parse/modules/pass_module.py`
- `src/parse/rdc_parse_pipeline.py`
- `src/parse/environment/cos_params.py`

建议扩展方式：

- 新实体优先新增独立模块
- 编排层只做 action 遍历、关系聚合、索引写入
- 保持模块接口稳定：`extract_*` / `persist_*`
