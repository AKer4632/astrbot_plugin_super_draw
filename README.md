# AstrBot 超级生图插件

这是一个给 AstrBot 使用的统一图像生成插件。它把 Gemini、OpenAI、Grok、Z-Image、Jimeng 等不同接口整理成同一种使用方式：用户只需要发 `/生图`，插件会自动读取提示词、参考图、预设、当前模型和限制规则，然后把生成结果发回聊天窗口。

这个项目是按 HOP（面向人类编程）规范来写的。代码结构遵循一条很直白的主线：

```text
用户触发命令或 LLM 工具
-> main.py 触发
-> image.py / model.py / preset.py 执行指令
-> data.py / store.py 读写数据
-> provider/ 请求真实生图接口
-> task.py / tool/ 做后台清理和通用小工具
-> AstrBot 把结果发回聊天
```

## 项目特色

- 多供应商统一入口：同一个 `/生图` 命令可以切换 Gemini、OpenAI、Grok、Z-Image、Jimeng。
- 支持文生图：输入文字，生成图片。
- 支持图生图：消息图片、回复里的图片、`@用户`头像都可以作为参考图。
- OpenAI 已支持图生图：`gpt-image` 系列会走 OpenAI 图片编辑接口。
- 支持 LLM 工具调用：LLM 可以在对话中自动调用 `generate_image`。
- 支持预设：可以保存常用风格、比例和分辨率。
- 支持多 API Key 轮换：请求失败或重试时会自动换 Key。
- 支持用户限制：可以设置冷却时间、每日次数和参考图大小。
- 支持后台任务：自动清理缓存；Jimeng 可按配置自动签到领取积分。
- 代码可读性优先：文件名、函数名和注释都围绕“人先看懂”来写。

## 安装要求

- AstrBot `>= 4.20.1`
- Python `>= 3.10`
- 依赖见 [requirements.txt](./requirements.txt)

本插件不是独立程序，需要放进 AstrBot 插件目录后由 AstrBot 加载。

## 快速开始

1. 把插件目录放到 AstrBot 的插件目录里。
2. 在 AstrBot 插件配置中添加至少一个 `api_providers`。
3. 填入供应商名称、Base URL、API Key 和可用模型。
4. 重启 AstrBot 或重新加载插件。
5. 在聊天里发送：

```text
/生图 一只坐在窗边看雨的猫，柔和光线，电影感
```

如果要切换模型：

```text
/生图模型
/生图模型 2
```

## 用户命令

### `/生图`

生成图片。最常用的命令。

```text
/生图 一座漂浮在云层上的城市
```

使用预设：

```text
/生图 动漫风 蓝色头发的少女
```

使用图片作为参考图：

```text
发送一张图片，然后在同一条消息里写：
/生图 改成像素风头像
```

使用回复里的图片：

```text
回复一条带图片的消息：
/生图 改成赛博朋克风
```

使用头像作为参考图：

```text
/生图 做成 3D 手办风 @某个用户
```

### `/生图模型`

查看当前可用模型和当前正在使用的模型。

```text
/生图模型
```

切换模型。序号来自 `/生图模型` 的列表。

```text
/生图模型 2
```

### `/预设`

查看所有预设。

```text
/预设
```

添加一个普通预设：

```text
/预设 添加 动漫风:anime style, clean line art, bright colors
```

添加一个带参数的 JSON 预设：

```text
/预设 添加 壁纸:{"prompt":"cinematic wallpaper, rich detail","aspectRatio":"16:9","resolution":"2K"}
```

删除预设：

```text
/预设 删除 动漫风
```

## LLM 工具调用

插件会注册一个名为 `generate_image` 的工具。开启 `enable_llm_tool` 后，LLM 可以自动调用它。

工具参数：

| 参数                 | 说明                                      |
| ------------------ | --------------------------------------- |
| `prompt`           | 生图提示词，必填                                |
| `aspectRatio`      | 图片宽高比，比如 `1:1`、`16:9`、`9:16`，不确定可用 `自动` |
| `resolution`       | 图片质量或分辨率，比如 `1K`、`2K`、`4K`              |
| `avatarReferences` | 头像参考图，可填 `self`、`sender` 或 QQ 号         |

代码里也兼容旧参数名 `aspect_ratio` 和 `avatar_references`，这样旧调用不会突然失效。

## 供应商支持

| 类型              | 文生图 | 图生图 | 分辨率  | 宽高比  | 说明                        |
| --------------- | --- | --- | ---- | ---- | ------------------------- |
| `gemini`        | 支持  | 支持  | 支持   | 支持   | Gemini 原生图片接口             |
| `gemini_openai` | 支持  | 支持  | 部分支持 | 部分支持 | OpenAI 兼容格式的 Gemini 接口    |
| `openai`        | 支持  | 支持  | 支持   | 支持   | OpenAI 图片接口；有参考图时走 edits  |
| `grok`          | 支持  | 支持  | 支持   | 支持   | xAI Grok 图片接口             |
| `z_image_gitee` | 支持  | 不支持 | 支持   | 支持   | Gitee AI Z-Image          |
| `jimeng2api`    | 支持  | 支持  | 支持   | 支持   | 即梦 2API / jimeng-api 兼容接口 |

说明：

- 不是每个模型都支持同样的参数。插件会尽量按供应商能力保留或忽略参数。
- OpenAI 图生图需要使用支持图片编辑的模型。推荐使用 `gpt-image` 系列。
- Z-Image 目前只走文生图，如果消息里带参考图会给出提示。
- Jimeng 自动签到只适用于提供对应接口的直连服务，中转服务不一定支持。

## 配置说明

### 基础配置

| 配置项               | 默认值    | 说明                |
| ----------------- | ------ | ----------------- |
| `enable_llm_tool` | `true` | 是否允许 LLM 自动调用生图工具 |

### `api_providers`

这里配置真实的生图供应商。可以配置多个，模型切换时会用 `供应商名称/模型名称` 来定位。

| 配置项                | 说明                                |
| ------------------ | --------------------------------- |
| `__template_key`   | 供应商类型，比如 `gemini`、`openai`、`grok` |
| `name`             | 供应商显示名，建议写短一点，比如 `OpenAI`         |
| `base_url`         | API 地址；为空时部分供应商会使用代码里的默认地址        |
| `proxy`            | 代理地址，比如 `http://127.0.0.1:7890`   |
| `api_keys`         | API Key 列表，可以填多个                  |
| `available_models` | 这个供应商下可切换的模型列表                    |

模型显示格式：

```text
供应商名称/模型名称
```

例如：

```text
OpenAI/gpt-image-2
Gemini/gemini-2.5-flash-image
```

### `generation`

| 配置项                    | 默认值     | 说明                  |
| ---------------------- | ------- | ------------------- |
| `model`                | 空       | 当前模型；空值会默认使用第一个可用模型 |
| `timeout`              | `180`   | 请求超时时间，单位秒          |
| `max_retry_attempts`   | `3`     | 失败后最多重试次数           |
| `max_concurrent_tasks` | `3`     | 同时进行的生图任务数量         |
| `default_aspect_ratio` | `自动`    | 默认宽高比               |
| `default_resolution`   | `1K`    | 默认分辨率               |
| `show_generation_info` | `false` | 是否在结果里显示耗时和数量       |
| `show_model_info`      | `false` | 是否在结果里显示模型名称        |

### `user_limits`

| 配置项                  | 默认值     | 说明               |
| -------------------- | ------- | ---------------- |
| `rate_limit_seconds` | `0`     | 同一个用户两次生图之间的冷却时间 |
| `max_image_size_mb`  | `10`    | 参考图最大大小          |
| `enable_daily_limit` | `false` | 是否开启每日次数限制       |
| `daily_limit_count`  | `10`    | 每个用户每天最多生图次数     |

### `cache`

| 配置项                      | 默认值   | 说明            |
| ------------------------ | ----- | ------------- |
| `max_cache_count`        | `100` | 最多保留多少张缓存图片   |
| `cleanup_interval_hours` | `24`  | 每隔多少小时清理一次旧缓存 |

### `presets`

预设可以写成普通文本：

```text
动漫风:anime style, clean line art
```

也可以写成 JSON，覆盖默认比例和分辨率：

```text
壁纸:{"prompt":"cinematic wallpaper","aspectRatio":"16:9","resolution":"2K"}
```

为了兼容旧配置，JSON 里的 `aspect_ratio` 也能继续读取。

## 项目结构

```text
main.py              AstrBot 插件入口，只接收触发并分发给具体指令
image.py             生图指令，负责 /生图 和 LLM 工具生图流程
model.py             模型指令，负责查看和切换当前模型
preset.py            预设指令，负责查看、添加、删除和套用预设
data.py              插件数据账本，保存配置、用量、预设和当前模型
store.py             插件运行时仓库，保存 provider、锁、后台任务和目录
task.py              后台任务，负责缓存清理和 Jimeng 自动签到
astrbotTool.py       LLM 工具入口，把 LLM 调用转给 image.py
provider/            各供应商的真实请求代码
tool/                通用小工具，比如文件、图片、时间、文本处理
```

按 HOP 思路读代码时，可以从 [main.py](./main.py) 开始。看到命令后跳到对应主体文件：

- `/生图` 看 [image.py](./image.py)
- `/生图模型` 看 [model.py](./model.py)
- `/预设` 看 [preset.py](./preset.py)
- 供应商请求看 [provider](./provider)
- 数据结构看 [data.py](./data.py)

## 维护方式

### 新增一个供应商

1. 在 `provider/` 下新增一个供应商文件。
2. 继承 `BaseProvider`。
3. 实现 `getAbilities()`，告诉插件支持文生图、图生图、比例、分辨率中的哪些能力。
4. 实现 `generateOnce()`，把统一的 `ImageRequest` 转成这个供应商需要的请求。
5. 在 `provider/__init__.py` 里加入这个供应商。
6. 在 `_conf_schema.json` 里加入对应配置模板。

### 修改生图流程

优先看 [image.py](./image.py)。它按这个顺序写：

```text
检查用户限制
-> 读取提示词和预设
-> 读取参考图
-> 创建任务 ID
-> 后台请求供应商
-> 保存图片
-> 发送结果
```

### 修改配置读取

看 [data.py](./data.py)。这里是插件的数据账本，所有配置字段都集中在这里转成清楚的数据对象。

## 常见问题

### 为什么我发了图片却没有进入图生图？

先检查当前模型是否支持图生图。可以用 `/生图模型` 切换到支持图生图的供应商和模型。

### 为什么同样的比例在不同供应商效果不一样？

不同供应商接受的比例和尺寸不完全一致。插件会尽量转换，但最终效果仍以供应商接口为准。

### 为什么 OpenAI 图生图失败？

请确认当前模型是 `gpt-image` 系列。DALL-E 系列不支持这里的 OpenAI 图生图流程，只建议用于文生图。

### 缓存图片会一直增长吗？

不会。`task.py` 会按 `cache.cleanup_interval_hours` 定时清理，最多保留 `cache.max_cache_count` 张。


