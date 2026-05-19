# AstrBot 超级生图插件

给 AstrBot 使用的图像生成插件。基于 OpenAI 官方 SDK，以 OpenAI 兼容格式调用 `gpt-image-2` 模型，支持文生图和图生图。

代码按 HOP（面向人类编程）规范来写，遵循一条直白的主线：

```text
用户触发命令或 LLM 工具
-> main.py 接收触发
-> 提取提示词、参考图、预设
-> generate.py 执行生图
-> data.py 管理配置和用量
-> tool/ 做文件保存和格式转换
-> AstrBot 把结果发回聊天
```

## 功能特色

- **OpenAI 兼容格式**：用 OpenAI 官方 SDK，请求格式兼容 OpenAI 接口，支持各种中转服务。
- **文生图**：输入文字，生成图片。
- **图生图**：消息图片、回复链图片、`@用户`头像、合并转发消息、URL、本地文件都可以作为参考图。
- **LLM 工具调用**：LLM 可以自动调用 `generate_image` 工具，支持同时传入 `imageUrls`（URL 列表）和 `imagePaths`（本地路径列表）。
- **后台任务**：生图是后台异步执行，不阻塞 LLM 响应。
- **多 Key 轮换**：请求失败时自动切换下一个 API Key。
- **预设**：可以保存常用风格、比例和质量。
- **用户限制**：支持冷却时间和每日次数限制。

## 安装要求

- AstrBot `>= 4.20.1`
- Python `>= 3.10`
- 依赖见 [requirements.txt](./requirements.txt)

本插件需要放进 AstrBot 插件目录由 AstrBot 加载，不是独立程序。

## 快速开始

1. 把插件目录放到 AstrBot 的插件目录里。
2. 在 AstrBot 插件配置中填入 API Key 和 Base URL（使用中转服务时填写中转地址）。
3. 重启 AstrBot 或重新加载插件。
4. 在聊天里发送：

```text
/生图 一只坐在窗边看雨的猫，柔和光线，电影感
```

## 用户命令

### `/生图`

生成图片。

```text
/生图 一座漂浮在云层上的城市
```

使用图片作为参考图（消息中的图片会自动作为参考图）：

```text
发送一张图片，然后在同一条消息里写：
/生图 改成像素风头像
```

使用回复里的图片：

```text
回复一条带图片的消息：
/生图 改成赛博朋克风
```

使用 `@用户` 头像作为参考图（`@` 不需要在消息开头）：

```text
/生图 做成 3D 手办风 @某个用户
```

使用本地文件作为参考图：

```text
/生图 保持构图换成水彩风格 d:\images\photo.jpg
```

使用预设：

```text
/生图 动漫风 蓝色头发的少女
```

### `/预设`

查看所有预设：

```text
/预设
```

添加预设：

```text
/预设 添加 动漫风:anime style, clean line art, bright colors
```

删除预设：

```text
/预设 删除 动漫风
```

## LLM 工具调用

插件注册了一个名为 `generate_image` 的工具。LLM 可以自动调用它。

工具参数：

| 参数          | 说明                                                     |
| ------------- | -------------------------------------------------------- |
| `prompt`      | 生图提示词，必填                                         |
| `aspectRatio` | 宽高比，可选 `auto`、`1:1`、`2:3`、`3:2`、`9:16`、`16:9` |
| `quality`     | 质量，可选 `low`、`medium`、`high`、`auto`               |
| `imageUrls`   | 图片 URL 列表，作为参考图                                |
| `imagePaths`  | 本地图片路径列表，作为参考图                             |

LLM 调用时，插件会自动从消息上下文中提取：
- 消息中的图片
- 回复链里的图片
- 合并转发消息里的图片
- `@用户` 的头像（`@` 不需要在消息开头）

这些上下文中的图片会和 `imageUrls`、`imagePaths` 合并，一起作为参考图。

### 调用示例

纯文生图：

```python
generate_image(prompt="一只橘色的猫在阳光下睡觉")
```

图生图（LLM 自己知道提供 URL）：

```python
generate_image(
    prompt="把这张图换成梵高风格",
    imageUrls=["https://example.com/cat.jpg"]
)
```

图生图（使用本地文件）：

```python
generate_image(
    prompt="保持人物替换背景",
    imagePaths=["d:\\images\\portrait.jpg"]
)
```

多源参考图叠加：

```python
generate_image(
    prompt="结合这两张图的风格创作",
    imageUrls=["https://example.com/style1.jpg"],
    imagePaths=["d:\\images\\style2.jpg"]
)
```

## 配置说明

### 基础配置

| 配置项           | 默认值        | 说明                                    |
| ---------------- | ------------- | --------------------------------------- |
| `api_keys`       | `[]`          | API Key 列表，可以填多个                |
| `base_url`       | `""`          | API 地址，为空时使用 OpenAI 默认地址    |
| `model`          | `gpt-image-2` | 模型名称（默认 `gpt-image-2`）          |
| `proxy`          | `null`        | HTTP 代理，例如 `http://127.0.0.1:7890` |
| `timeout`        | `180`         | 请求超时秒数                            |
| `max_retry`      | `3`           | 最大重试次数                            |
| `max_concurrent` | `3`           | 最大并发任务数                          |

### `generation`

| 配置项                 | 默认值   | 说明                |
| ---------------------- | -------- | ------------------- |
| `default_aspect_ratio` | `auto`   | 默认宽高比          |
| `default_quality`      | `medium` | 默认质量（对应 2K） |
| `show_generation_info` | `false`  | 是否显示耗时和数量  |

### `user_limits`

| 配置项               | 默认值  | 说明                           |
| -------------------- | ------- | ------------------------------ |
| `rate_limit_seconds` | `0`     | 同一用户两次生图之间的冷却时间 |
| `max_image_size_mb`  | `10`    | 参考图最大大小（MB）           |
| `enable_daily_limit` | `false` | 是否开启每日次数限制           |
| `daily_limit_count`  | `10`    | 每个用户每天最多生图次数       |

### `presets`

预设格式：

```text
动漫风:anime style, clean line art, bright colors
```

也可以写成 JSON 覆盖默认参数：

```text
壁纸:{"prompt":"cinematic wallpaper, rich detail","aspectRatio":"16:9","quality":"high"}
```

## 项目结构

```text
main.py              AstrBot 插件入口，接收触发并分发
generate.py           通用图片生成库，与 AstrBot 无关
data.py               插件数据账本，保存配置、用量、预设
tool/                 通用小工具（文件保存、图片格式转换）
tool/file.py          文件操作：保存图片、清理缓存目录
tool/picture.py       图片操作：检测格式、转换格式
```

按 HOP 思路读代码时，从 [main.py](./main.py) 开始：

- `/生图` 或 LLM 工具触发 -> `ImageTool.run()` -> `ImageGenerate.execute()`
- 预设操作 -> `PresetManage.execute()`
- 数据和配置 -> [data.py](./data.py)
- 生图核心逻辑 -> [generate.py](./generate.py)

## 生图流程

```
用户发送命令或 LLM 调用
-> main.py 接收
-> 提取 prompt、参考图（消息图片/@头像/合并转发/URL/本地文件）
-> 检查用户限制（冷却、每日次数、参考图大小）
-> 调用 generate.py 的 ImageGenerator.generate()
   - 有参考图走图生图（images.edit）
   - 无参考图走文生图（images.generate）
   - 自动重试和 Key 轮换
-> 保存图片到缓存目录
-> AstrBot 把结果发回聊天
```

## 常见问题

### 为什么有参考图却没有进入图生图？

检查参考图是否可访问：消息图片是否还在、URL 是否有效、文件路径是否正确。

### 为什么生图失败？

1. 确认 API Key 有效
2. 确认 Base URL 正确（使用中转时，中转服务需要支持 OpenAI 兼容格式）
3. 确认模型支持图生图（`gpt-image-2` 支持）

### 缓存图片会一直增长吗？

不会。插件会定时清理缓存目录，保留最新生成的部分图片。
