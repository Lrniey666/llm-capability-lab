"""把 Router 接進 Discord bot 的最小範例。

重點不在 discord.py 怎麼寫，而在三件事：
  1. Router 讓 429 對使用者隱形——同一家先換 KEY2 / KEY3，再換下一家，不會噴錯誤訊息
  2. 用 router.achat()：阻塞的 HTTP 呼叫會自動丟到執行緒，不會卡住 event loop
  3. 自己先擋一層每人冷卻，比讓 provider 擋你划算

執行前：pip install discord.py，並在 .env 加上 DISCORD_TOKEN。
"""

from __future__ import annotations

import os
import time
from collections import defaultdict

from llmclab import AllProvidersFailed, Router

SYSTEM_PROMPT = "你是一個簡潔的助手，用繁體中文回答，盡量控制在三句話內。"
USER_COOLDOWN_S = 10
MAX_REPLY_CHARS = 1800  # Discord 單則訊息上限 2000，留點餘裕

# from_env() 會載入 .env，並只採用金鑰已就位的那幾家；
# 順序即策略：延遲低的先試，額度大的墊後，本機 Qwen 保底。
router = Router.from_env(retries_per_key=1, timeout=45)

_last_call: dict[int, float] = defaultdict(float)


def _cooldown_left(user_id: int) -> float:
    return max(0.0, USER_COOLDOWN_S - (time.time() - _last_call[user_id]))


async def generate(prompt: str) -> tuple[str, str]:
    """回傳 (回覆文字, 實際使用的 provider)。"""
    result = await router.achat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=500,
    )
    return result.text[:MAX_REPLY_CHARS], result.provider


def main() -> None:
    import discord

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"已登入：{client.user}")

    @client.event
    async def on_message(message: "discord.Message"):
        if message.author.bot or not message.content.startswith("!ask "):
            return

        left = _cooldown_left(message.author.id)
        if left > 0:
            await message.reply(f"冷卻中，{left:.0f} 秒後再試。", mention_author=False)
            return
        _last_call[message.author.id] = time.time()

        prompt = message.content[len("!ask "):].strip()
        if not prompt:
            await message.reply("用法：`!ask 你的問題`", mention_author=False)
            return

        async with message.channel.typing():
            try:
                reply, provider = await generate(prompt)
            except AllProvidersFailed:
                await message.reply("雲端與本機保底目前都不可用，晚點再試。", mention_author=False)
                return
            except Exception as exc:  # noqa: BLE001
                print(f"生成失敗：{exc}")
                await message.reply("出了點問題，已記錄。", mention_author=False)
                return

        await message.reply(f"{reply}\n-# via {provider}", mention_author=False)

    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("請在 .env 設定 DISCORD_TOKEN")
    client.run(token)


if __name__ == "__main__":
    main()
