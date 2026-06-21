# AstrBot 超级生图插件

AstrBot 的图像生成插件。用户说要画图，插件调用 OpenAI 或 Gemini 接口生成图片，发回聊天。就这么简单。

**核心能力：**
- 文生图：发一段文字描述，生成图片
- 图生图：消息里带图片就自动当参考图，模型会参考着画
- 多接口：同时配置多个 OpenAI 兼容接口和 Gemini 接口，挂了自动换下一个
- 多 Key 轮换：同一个接口配置多个 API Key，被限流了自动换下一个

## 安装

- AstrBot `>= 4.20.1`
- Python `>= 3.10`

放进 AstrBot 插件目录，在配置面板填好 API Key，重启即可。

## 快速开始

```text
/生图 一只坐在窗边看雨的猫，柔和光线，电影感
```

## 用户命令

| 命令                 | 说明               |
| -------------------- | ------------------ |
| `/生图 提示词`       | 文生图或图生图     |
| `/生图模型 [数字]`   | 查看或切换模型     |
| `/生图队列`          | 查看运行中的任务   |
| `/生图开关`          | 开启或关闭生图功能 |
| `/生图取消 <任务ID>` | 取消指定生图任务   |
| `/预设 [子命令]`     | 查看/添加/删除预设 |

### `/生图` 使用说明

直接把文字和图片原样透传给生图模型，不做任何参数解析：

```text
/生图 一只坐在窗边看雨的猫，柔和光线，电影感
```

如果需要精确控制尺寸、质量、数量等参数，请让 LLM 自动调用 `super_draw` 工具。

### 参考图来源（自动识别）

- 消息中的图片
- 被回复消息中的图片
- 合并转发消息中的图片
- `@某个用户` 的头像（`@` 不在消息开头时生效）
- 消息中的 HTTP/HTTPS 图片 URL

### `/生图模型`

```text
/生图模型          # 查看模型列表
/生图模型 2        # 切换到第 2 个模型
```

### `/预设`

```text
/预设                        # 查看预设列表
/预设 查看 手办化              # 查看预设详情
/预设 添加 水彩:柔和水彩风格    # 添加预设
/预设 删除 水彩               # 删除预设
```

使用预设：

```text
/生图 手办化 一只猫            # 预设内容会自动拼到提示词前面
```

## LLM 工具

工具名：`super_draw`

| 参数      | 类型    | 说明                                              |
| --------- | ------- | ------------------------------------------------- |
| `prompt`  | string  | 必填，图片内容描述                                |
| `size`    | string  | 可选，`auto`、`1:1`、`16:9`、`9:16`、`3:2`、`2:3` |
| `quality` | string  | 可选，`auto`、`low`、`medium`、`high`             |
| `n`       | integer | 可选，生成数量 1-4                                |
| `urls`    | string  | 可选，参考图 URL，逗号分隔                        |

## 项目结构

```text
main.py               AstrBot 入口，接命令和 LLM 工具调用，调用生图流程
data.py               读取配置、用户限制、预设管理、模型切换
generate.py           调用 OpenAI 或 Gemini 生图接口，返回图片字节
tool/file.py          保存图片、清理缓存
tool/picture.py       通过文件头判断图片格式
```

## 工作流程

```
用户命令 / LLM 工具
  → main.py 取出提示词和参考图
  → data.py 检查用户限制、解析预设
  → generate.py 调用生图接口（失败自动换下一个 provider / key）
  → tool/file.py 保存图片
  → 发回聊天
```

## 配置项

| 配置                              | 说明                        |
| --------------------------------- | --------------------------- |
| `enabled`                         | 插件总开关                  |
| `enable_llm_tool`                 | 是否注册 LLM 工具           |
| `api_providers`                   | 生图供应商列表              |
| `generation.model`                | 当前模型（供应商名/模型名） |
| `generation.default_quality`      | 默认质量                    |
| `generation.default_size`         | 默认比例                    |
| `generation.save_format`          | 图片保存格式                |
| `generation.max_retry_attempts`   | 单个 provider 的重试次数    |
| `generation.max_concurrent_tasks` | 最大并发任务数              |
| `user_limits.rate_limit_seconds`  | 冷却时间（秒）              |
| `user_limits.enable_daily_limit`  | 是否限制每日次数            |
| `user_limits.daily_limit_count`   | 每日生图上限                |
| `presets`                         | 预设提示词列表              |

## 如何新增接口

在 `generate.py` 里加一个 `_callXxx()` 函数，然后在 `makeImages()` 的分支里加一行判断即可。
