# nonebot-plugin-music-score-reactor

> 同系列插件与部署/架构文档：[`MortisBot/qqbot-plugins`](https://github.com/MortisBot/qqbot-plugins)（索引与文档仓）

群聊收到图片时，调用**你自己配置的** OpenAI 兼容视觉模型判断它是不是音游成绩结算/分享图；
命中后通过 NapCat 的 `set_msg_emoji_like` 给原消息贴一个 QQ 表情，不发送文字。

插件还包含三个可选能力：

- **随机贴表情**：按概率给普通文字消息贴表情，并按本群历史频数加权挑选；
- **跟随贴表情**：别人给消息贴表情时，按去重人数与条件概率决定是否跟贴同一个表情；
- **频数学习**：`group_msg_emoji_like` 通知本地统计，带时间衰减与原子落盘。

默认**完全关闭**：`MUSIC_SCORE_ENABLED=false`，且 `MUSIC_SCORE_GROUPS` 为空时不生效。

## 安装

```bash
nb plugin install nonebot-plugin-music-score-reactor
```

或在 `pyproject.toml` 中加入 `nonebot-plugin-music-score-reactor` 后安装并加载插件。
需要 OneBot v11 实现（NapCat）提供 `set_msg_emoji_like` 与 `group_msg_emoji_like` 通知。

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MUSIC_SCORE_ENABLED` | `false` | 总开关；默认关闭 |
| `MUSIC_SCORE_GROUPS` | 空 | 生效群列表，逗号分隔；**空=不生效** |
| `MUSIC_SCORE_VISION_BASE_URL` | 空 | OpenAI 兼容 `chat/completions` 地址；**空=禁用视觉调用** |
| `VISION_API_KEY` | 空 | 视觉服务 API key |
| `VISION_MODEL` | `gpt-4o-mini` | 模型名，按服务商填写 |
| `VISION_TIMEOUT` | `30` | 单次请求超时（秒） |
| `VISION_SUPPORTS_BASE64` | `true` | 是否允许下载图片后以 data URL 重试 |
| `MUSIC_SCORE_REACTION_EMOJI_ID` | `297` | 成绩图命中的表情 ID（NapCat） |
| `MUSIC_SCORE_IGNORE_USERS` | 空 | 忽略的用户 ID，逗号分隔 |
| `MUSIC_SCORE_DETECT_ROBOTS` | `true` | 查询群成员 `is_robot` 并跳过官方机器人 |
| `MUSIC_SCORE_ROBOT_CACHE_TTL` | `3600` | 机器人标记缓存秒数 |
| `MUSIC_SCORE_MIN_FILE_KB` | `8` | 小于该大小的图片跳过 |
| `MUSIC_SCORE_SKIP_GIF` | `true` | 跳过 `.gif` / 动画表情 |
| `MUSIC_SCORE_MAX_IMAGES_PER_MESSAGE` | `1` | 每条消息最多检查几张图 |
| `MUSIC_SCORE_MAX_CONCURRENT` | `2` | 同时进行的视觉请求数 |
| `MUSIC_SCORE_RATE_LIMIT_PER_MIN` | `10` | 全局每分钟视觉请求上限，`0`=不限 |
| `MUSIC_SCORE_VERDICT_TTL` | `900` | 识别结果缓存秒数 |
| `MUSIC_SCORE_VERDICT_CACHE_MAX` | `512` | 识别结果缓存条数 |
| `MUSIC_SCORE_RANDOM_ENABLED` | `true` | 随机贴表情开关（仍需总开关与群列表） |
| `MUSIC_SCORE_RANDOM_RATE` | `0.002` | 每条文字消息随机贴的概率 |
| `MUSIC_SCORE_RANDOM_EMOJI_IDS` | `424,10068` | 随机表情候选，逗号分隔 |
| `MUSIC_SCORE_STATS_ENABLED` | `true` | 频数学习开关 |
| `MUSIC_SCORE_STATS_EXCLUDE_EMOJI_IDS` | `297` | 不参与学习的表情 |
| `MUSIC_SCORE_STATS_POWER` | `1.2` | 频数权重指数 |
| `MUSIC_SCORE_STATS_HALF_LIFE` | `14` | 时间衰减半衰期（天），`0`=关闭衰减 |
| `MUSIC_SCORE_STATS_MIN_SAMPLES` | `5` | 学习池最少表情数，不足则回退固定列表 |
| `MUSIC_SCORE_STATS_STORE_PATH` | `data/music_score_reactor/reaction_stats.json` | 统计文件路径 |
| `MUSIC_SCORE_STATS_SAVE_DEBOUNCE` | `10` | 写盘防抖秒数 |
| `MUSIC_SCORE_FOLLOW_ENABLED` | `true` | 跟随贴表情开关 |
| `MUSIC_SCORE_FOLLOW_MAX_P` | `1.0` | 跟随概率上限 |
| `MUSIC_SCORE_FOLLOW_STATE_TTL` | `21600` | 跟贴计数保留秒数 |
| `MUSIC_SCORE_FOLLOW_STATE_MAX` | `5000` | 跟贴计数条目上限 |
| `MUSIC_SCORE_VISION_MAX_IMAGE_KB` | `5120` | base64 重试的图片大小上限 |
| `MUSIC_SCORE_HTTP_PROXY` | 空 | 可选 HTTP 代理 |

### 服务商示例（OpenAI 兼容）

智谱开放平台：

```dotenv
MUSIC_SCORE_VISION_BASE_URL=https://open.bigmodel.cn/api/paas/v4/chat/completions
VISION_API_KEY=<your-key>
VISION_MODEL=glm-4.6v-flash
```

OpenAI：

```dotenv
MUSIC_SCORE_VISION_BASE_URL=https://api.openai.com/v1/chat/completions
VISION_API_KEY=<your-key>
VISION_MODEL=gpt-4o-mini
```

自建网关：把 `MUSIC_SCORE_VISION_BASE_URL` 指向兼容 `/chat/completions` 的完整地址即可；
模型是否接受图片 URL、是否接受 data URL 由服务商决定，可用 `VISION_SUPPORTS_BASE64` 控制回退。

### 启用示例

```dotenv
MUSIC_SCORE_ENABLED=true
MUSIC_SCORE_GROUPS=<群号>
MUSIC_SCORE_VISION_BASE_URL=https://api.openai.com/v1/chat/completions
VISION_API_KEY=<your-key>
VISION_MODEL=gpt-4o-mini
```

## 使用

无需命令，满足条件时自动工作：

1. 群消息含图片 → 本地过滤（动画表情、小图、gif、无 URL）→ 视觉二分类；
2. 判定为成绩图 → 对原消息贴 `MUSIC_SCORE_REACTION_EMOJI_ID`；
3. 文字消息 → 按 `MUSIC_SCORE_RANDOM_RATE` 随机贴一个表情；
4. 收到表情回应通知 → 学习频数，并按条件概率决定是否跟贴。

判定为「否」、请求失败或超时都只记日志，不回复、不影响其它插件。

## 隐私

- 启用后，图片 **URL 或图片字节（base64 data URL）** 会发送到 `MUSIC_SCORE_VISION_BASE_URL`
  指向的第三方服务；提示词只包含通用的分类说明，不包含群号或用户信息。
- 视觉请求可能携带你配置的 API key；请只使用可信服务商，并妥善保管密钥。
- 频数统计仅保存在本地 `MUSIC_SCORE_STATS_STORE_PATH`，包含群 ID 与表情 ID，不包含消息内容。
- 插件没有遥测或额外上报；关闭 `MUSIC_SCORE_ENABLED` 或清空 `MUSIC_SCORE_GROUPS`
  即可完全停止外发与贴表情。
- NapCat 自身可能记录消息/图片，请按其隐私设置管理。

## 依赖与边界

- 贴表情依赖 NapCat 扩展 API `set_msg_emoji_like`；学习/跟随依赖
  `group_msg_emoji_like` 通知。缺失时图片分类仍可运行，但不会产生任何表情。
- `group_msg_emoji_like` 没有专用适配器模型，插件按通用 `NoticeEvent` 读取字段。
- 只支持 OneBot v11；私聊消息不处理。
- `MUSIC_SCORE_GROUPS` 为空时所有群都不生效（安全默认），不会“全群开启”。

## 维护与排障

- 临时停用：`MUSIC_SCORE_ENABLED=false` 后重启；或清空 `MUSIC_SCORE_GROUPS`。
- 视觉接口 401/403/429 不会触发 base64 重试；检查 key、配额与限流。
- 统计文件损坏会被重命名为 `*.corrupt-<时间戳>`，本次从空统计开始。
- 删除统计文件不会影响识别；学习池不足时随机表情回退到固定候选列表。
- 日志中可能包含群 ID、用户 ID 与图片 URL 前缀，公开日志前请先脱敏。

## License

MIT
