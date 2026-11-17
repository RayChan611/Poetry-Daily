# scripts

两个脚本都依赖同目录下的 `ai_client.py`（OpenAI 兼容接口封装）与 `feishu_notify.py`（飞书卡片推送），这两份没放进来。

- `saohua.py` — 「此刻」。语料批次 `quotes.json` / `quotes.N.json`，指针 `quotes_state.json`，去重 `saohua_history.json`。
- `daily_poem.py` — 「每日诗词」。纯 AI 生成，无历史机制，是这套东西里最不可靠的一个（诗句由模型挑、赏析由模型写，真伪无法核）。

webhook 从 `.saohua_webhook` 文件读，不写死在代码里。