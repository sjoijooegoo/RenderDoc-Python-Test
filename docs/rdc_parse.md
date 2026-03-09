# RDC Parse 解析框架（中文完整版）

本文档定义当前仓库 `rdc_parse` 的**生产可用输出契约**，用于：

- 本地解析调试
- 数据平台上报
- 跨批次对比与去重分析

---

## 1. 目标与范围

`rdc_parse` 负责解析单个 RenderDoc 捕获文件（`.rdc`），输出以 `rdc_entry.json` 为中心的清单式数据集。

设计目标：

- 入口清单稳定（manifest-first）
- 目录与命名固定，便于平台接入
- 三类实体（Material / Texture / Shader）独立 JSON 化
- 重资源（纹理图片、Shader 源码）按需导出
- 索引可校验、可去重、可追踪

---

## 2. 固定约定

### 2.1 输出根目录

输入 `xxx.rdc` 时，输出固定为：

- `output/xxx/rdc_entry.json`

说明：

- `xxx` 取 `.rdc` 文件名（去后缀）并做安全化（非法字符转 `_`）。
- `output` 路径、入口文件名固定，不通过参数改写。

### 2.2 固定 schema 模式

当前任务内部固定使用 revision-1（不需要传 `schema=1`）。

### 2.3 固定目录名

在 `output/xxx/` 下，三类目录固定：

- `rdc_material/`
- `rdc_texture/`
- `rdc_shader/`

---

## 3. 运行参数

当前建议使用参数：

- `rdc` / `input` / `file`：输入 `.rdc` 路径
- `export_texture_assets=true/false`（默认 `true`）
  - 控制是否导出纹理图片 `image.png`
- `export_shader_assets=true/false`（默认 `true`）
  - 控制是否导出 shader 源码文件

补充说明：

- Shader JSON 始终导出（逻辑固定启用）。
- `include_context_events` 参数当前仍可传入，但不会进入当前 artifacts 输出模型。

---

## 4. 解析流程（高层）

1. 加载 capture 与 replay controller。
2. 遍历 draw/dispatch 事件。
3. 提取 shader、纹理、采样器、常量布局等信息。
4. 生成稳定 key（material/shader/texture compare key）。
5. 聚合成 material 级别关系。 
6. 落盘三类实体 JSON。 
7. 生成三类索引（`id/path/sha256`）。
8. 生成入口清单 `rdc_entry.json`。

流程图参考：

![RDC Parse Flow](assets/rdc_parse_flow_full_v1.png)

---

## 5. 入口清单：`rdc_entry.json`

示例：

```json
{
  "schema_version": "1.1.0",
  "parser_version": "rdc_parse_v1.1.0",
  "generated_at": "2026-03-09T12:34:56.123456+00:00",
  "capture_file": "1.rdc",
  "capture_id": "cap:...",
  "summary": {
    "material_count": 296,
    "texture_count": 405,
    "shader_count": 233,
    "texture_export_error_count": 12
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
    }
  }
}
```

字段说明：

- `schema_version`：数据契约版本
- `parser_version`：解析实现版本
- `generated_at`：UTC 生成时间
- `capture_file`：仅文件名（不含绝对路径）
- `capture_id`：由 capture 文件元信息（name/size/mtime）生成的指纹
- `summary`：快速统计信息
- `artifacts`：三类数据集合入口

---

## 6. artifacts 结构

`artifacts` 按集合分组：

- `materials`
- `textures`
- `shaders`

每个集合结构：

```json
{
  "index": "<relative_index_path>",
  "count": 123
}
```

设计目的：

- 平台接入只需遍历集合，不依赖固定目录字符串拼接。
- `count` 用于快速一致性校验（与 index 长度比对）。

---

## 7. 索引文件契约

三类索引文件：

- `rdc_material/rdc_material_index.json`
- `rdc_texture/rdc_texture_index.json`
- `rdc_shader/rdc_shader_index.json`

索引项统一格式：

```json
[
  {
    "id": "...",
    "path": "rdc_material/.../rdc_material.json",
    "sha256": "..."
  }
]
```

字段说明：

- `id`：集合内对比/去重 ID
- `path`：相对于 `rdc_entry.json` 所在目录的相对路径
- `sha256`：目标 JSON 文件内容哈希（完整性校验与变更检测）

---

## 8. 三类实体 JSON

### 8.1 Material：`rdc_material/<material_id>/rdc_material.json`

```json
{
  "material_base_key": "mat:...",
  "texture_json_paths": [
    "rdc_texture/ResourceId__123/rdc_texture.json"
  ],
  "shader_json_paths": [
    "rdc_shader/md5_xxx/rdc_shader.json"
  ]
}
```

说明：

- Material 文件保持最小化，只描述关系，不内嵌大块明细。
- 纹理与 shader 都通过 JSON 路径引用。

### 8.2 Texture：`rdc_texture/<texture_id>/rdc_texture.json`

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

- `image_path` / `image_sha256`：仅在纹理图片成功导出时存在。
- `export_error`：导出失败时存在。
- `texture_compare_key`：用于跨 capture 比对，不直接依赖 `ResourceId`。

### 8.3 Shader：`rdc_shader/<shader_id>/rdc_shader.json`

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
- 不导出源码时，`source_files` 仅保留文件名与行数元信息。

---

## 9. 关键 ID 与对比策略

### 9.1 Shader

- `shader_key` 优先使用源码 md5（`md5:...`），适合跨批次去重与 diff。

### 9.2 Texture

- `texture_compare_key` 基于语义特征生成：
  - `resource_name`
  - `format`
  - `width/height`
  - `mips`
  - `array_size`
- 索引中的 `id` 使用 `texture_compare_key`。

### 9.3 Material

- `material_base_key` 基于签名组合生成：
  - 纹理 compare 签名
  - 采样器签名
  - 常量布局签名
- 避免直接依赖 `ResourceId` 做主分组。

---

## 10. 资产导出行为矩阵

### 10.1 `export_texture_assets`

- `true`：尝试导出 `image.png`
- `false`：不导出图片，但仍导出 `rdc_texture.json`

### 10.2 `export_shader_assets`

- `true`：导出源码文件，`source_files[*].source_path` 可用
- `false`：不导出源码文件，`rdc_shader.json` 仍输出元信息

---

## 11. 平台上报建议

推荐接入顺序：

1. 读取 `rdc_entry.json`
2. 读取 `artifacts.<collection>.index`
3. 用 `sha256` 校验各 JSON 完整性
4. 读取实体 JSON 并入库
5. 按需拉取重资源：
   - `image.png`
   - shader 源码文件

推荐主键：

- Material：`material_base_key`
- Texture：`texture_compare_key`（可加 `image_sha256` 辅助）
- Shader：`shader_key`

---

## 12. 已知限制

- 部分纹理无法从 RenderDoc replay API 回读，`rdc_texture.json` 中会出现 `export_error`。
- `include_context_events` 暂未纳入当前 artifacts JSON 契约。
- 当前 material 输出是关系扁平化模型，不包含深层 variant/context 明细（如需可扩展为分析版 schema）。

---

## 13. 常用命令

全量导出（推荐默认）：

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
