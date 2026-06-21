# AstrBot 超级生图插件 v2

AstrBot 的图像生成插件，**用极少的代码撑起最强的通用性**：
- 统一入口：文生图、图生图、LLM 工具调用都走同一套引擎。
- 多接口适配：OpenAI 兼容接口、Gemini 官方接口，后续新增接口只需加一个适配器类。
- 多 Provider 容灾：主 Provider 挂了自动切下一个，Key 风控了自动轮下一个 Key。
- 格式转换：生成后可转 PNG / WebP / JPEG，省带宽。

## 安装

- AstrBot `>= 4.20.1`
- Python `>= 3.10`
- 依赖见 [requirements.txt](./requirements.txt)

放进 AstrBot 插件目录，配置 API Key，重启即可。

## 快速开始

```text
/生图 一只坐在窗边看雨的猫，柔和光线，电影感
```

## 用户命令

| 命令 | 说明 |
| ---- | ---- |
| `/生图 [参数] 提示词` | 文生图或图生图 |
| `/生图模型 [数字]` | 查看或切换模型 |
| `/生图队列` | 查看运行中的任务 |

### `/生图` 参数

在提示词前加上即可：

```text
/生图 --size 16:9 --quality high --n 2 一座漂浮在云端的未来城市
/生图 --format webp 一只橘猫
```

| 参数 | 取值 | 说明 |
| ---- | ---- | ---- |
| `--size` | `auto`、`1:1`、`16:9`、`9:16`、`3:2`、`2:3`、`1024x1024`、`1536x1024`、`1024x1536` | 图片比例或尺寸 |
| `--quality` | `auto`、`low`、`medium`、`high` | 生成质量（OpenAI 生效） |
| `--n` | 1-4 | 一次生成几张 |
| `--format` | `png`、`jpeg`、`webp` | 返回给用户的图片格式 |

### 参考图来源（自动识别）

- 消息中的图片
- 被回复消息中的图片
- 合并转发消息中的图片
- `@某个用户` 的头像（`@` 不在消息开头时生效）
- 消息中的 HTTP/HTTPS 图片 URL
- 本地文件路径（如 `d:\images\photo.jpg`）

### `/生图模型`

查看模型列表：

```text
/生图模型
```

切换模型：

```text
/生图模型 2
```

## LLM 工具

注册工具名：`generate_image`

| 参数 | 类型 | 说明 |
| ---- | ---- | ---- |
| `prompt` | string | 必填，生图提示词 |
| `size` | string | 可选，比例或尺寸 |
| `quality` | string | 可选，`low`/`medium`/`high` |
| `n` | integer | 可选，生成数量 1-4 |
| `urls` | array[string] | 可选，参考图 URL 列表 |

LLM 调用时，插件也会自动从当前消息上下文中提取参考图。

## 项目结构

```text
main.py               AstrBot 入口与命令/工具分发
generate.py           通用生图引擎 + OpenAI/Gemini 适配器
data.py               配置、用量、模型切换
tool/file.py          图片保存与格式转换
tool/picture.py       图片格式检测
```

### 如何新增接口

在 `generate.py` 里继承 `Adapter`，实现 `generate(prompt, images, size, quality, n)` 方法，然后在 `GenerateEngine._adapter_for` 里注册即可。无需改动 AstrBot 层。

## 配置项速览

| 配置 | 说明 |
| ---- | ---- |
| `enabled` | 插件总开关 |
| `enable_llm_tool` | 是否注册 LLM 工具 |
| `api_providers` | 一个或多个生图供应商 |
| `generation.model` | 当前模型 `供应商/模型名` |
| `generation.default_quality` | 默认质量 |
| `generation.default_size` | 默认比例 |
| `generation.save_format` | 返回图片格式 |
| `generation.max_retry_attempts` | 单 Provider 重试次数 |
| `generation.max_concurrent_tasks` | 最大并发任务数 |
| `user_limits` | 冷却、每日上限 |

## 原理概览

```
用户命令 / LLM 工具
 -> main.py 提取 prompt、参考图、flag
 -> data.py 检查限制、解析预设
 -> GenerateEngine 选择 Provider 并调用 Adapter
    -> OpenAIAdapter: images.generate / images.edit
    -> GeminiAdapter: models.generate_content
 -> 失败则自动切到下一个 Provider / Key
 -> tool/file.py 保存并转格式
 -> AstrBot 发送结果
```

## 常见问题

- **报错 `未配置生图 provider`**：检查 `api_providers` 里是否填了 `api_keys` 和 `available_models`。
- **OpenAI 报错 size 不对**：插件已经自动把 `auto` / `16:9` 等映射成合法尺寸。
- **Gemini 没图**：确认 `api_type` 为 `gemini`，并且已安装 `google-genai`。
