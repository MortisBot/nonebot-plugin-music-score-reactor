"""测试环境：初始化 NoneBot，禁止真实外网调用。"""

from __future__ import annotations

import os
import tempfile

import nonebot

# 包导入时会注册 matcher 并按默认配置构造客户端；先初始化 NoneBot。
os.environ["MUSIC_SCORE_ENABLED"] = "false"
os.environ["MUSIC_SCORE_VISION_BASE_URL"] = ""
os.environ["MUSIC_SCORE_STATS_STORE_PATH"] = os.path.join(
    tempfile.mkdtemp(prefix="score-reactor-test-"), "reaction_stats.json"
)
nonebot.init(driver="~none", command_start={"/"}, log_level="ERROR")
