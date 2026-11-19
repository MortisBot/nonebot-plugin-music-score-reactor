# nonebot-plugin-music-score-reactor

```text
群图片 ──▶ 视觉模型（OpenAI 兼容） ──▶ 是音游成绩图？
                                        ├─ 是 → 给原消息贴 Reaction
                                        └─ 否 → 什么也不做
```

## 是什么

收到群图片时，用**你自己配置的**视觉 API 判断它是否为音游成绩结算/分享图；命中后通过 NapCat 的 `set_msg_emoji_like` 给原消息贴一个 QQ 表情，不发送文字。

另外还带三个可选能力：随机贴表情、跟随别人贴表情、按群内频数学习。

## 安装

```bash
nb plugin install nonebot-plugin-music-score-reactor
```

手动：`pip install nonebot-plugin-music-score-reactor`，并在 `pyproject.toml` 中加入 `nonebot_plugin_music_score_reactor`。

## 配置

**视觉 API（必填）**

| 变量 | 说明 |
|:---:|:---|
| `MUSIC_SCORE_VISION_BASE_URL` | OpenAI 兼容的 `/chat/completions` 地址，如 `https://open.bigmodel.cn/api/paas/v4/chat/completions` |
| `MUSIC_SCORE_VISION_API_KEY` | API Key |
| `MUSIC_SCORE_VISION_MODEL` | 模型名，例如 `glm-4.6v-flash` |

**行为开关**

```dotenv
MUSIC_SCORE_ENABLED=true
MUSIC_SCORE_GROUPS=123456789
MUSIC_SCORE_REACTION_EMOJI_ID=297
MUSIC_SCORE_RANDOM_ENABLED=false
MUSIC_SCORE_FOLLOW_ENABLED=false
```

其余可选：`MUSIC_SCORE_RATE_LIMIT_PER_MIN`、`MUSIC_SCORE_MIN_FILE_KB`、`MUSIC_SCORE_SKIP_GIF`、`MUSIC_SCORE_STATS_*`。

## 使用

无需命令，自动生效。默认**完全关闭**：需要同时设置 `MUSIC_SCORE_ENABLED=true` 和非空的 `MUSIC_SCORE_GROUPS`。

## 注意

- 开启后群内图片会发送到你配置的第三方 API，请自行评估隐私与合规
- 贴表情依赖 NapCat 扩展 `set_msg_emoji_like`
- 适配器：OneBot v11（`~onebot.v11`）

## License

[MIT](./LICENSE)
