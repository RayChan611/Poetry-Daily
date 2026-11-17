# scripts

两个脚本都依赖同目录下的 `ai_client.py`（OpenAI 兼容接口封装）与 `feishu_notify.py`（飞书卡片推送），这两份没放进来。webhook 一律从 `.saohua_webhook` 文件读，不写死在代码里。

| 脚本 | 说明 |
|---|---|
| `saohua.py` | 「此刻」。语料批次 `quotes.json` / `quotes.N.json`，指针 `quotes_state.json`，去重 `saohua_history.json`（最近 1000 条）。 |
| `daily_poem.py` | 「每日诗词」。2026-11-17 重写：**诗句从语料库按序取，AI 只写赏析**。指针 `poem_state.json`，与「此刻」共用 `saohua_history.json` 做去重。语料取完就跳过当天，不重复推。 |

旧版 `daily_poem.py`（纯 AI 生成诗句）已不再使用，也没有存档，见主 README 的存档说明。
