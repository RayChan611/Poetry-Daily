#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日古诗词 / 文青句子 -> 飞书群机器人

每天推一首古诗词（词句为主，带作者与出处）配 AI 白话赏析，
偶尔推一句现代文青句子换口味。

用法:
  python3 daily_poem.py            # 生成并推送
  python3 daily_poem.py --dry-run  # 只生成不推送

webhook 复用「此刻」的 .saohua_webhook，可用 POEM_WEBHOOK 覆盖。
"""

import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai_client
import feishu_notify

BASE = os.path.dirname(os.path.abspath(__file__))
WEBHOOK_FILE = os.path.join(BASE, ".saohua_webhook")

TITLE = "每日诗词"

# 工作日推古诗词,周末推文青句子(换口味)
POEM_PROMPT = """请从中国古诗词中挑选一句或一联真正值得细品的名句（不要最烂大街的那几句，比如不要总是"床前明月光""但愿人长久"）。

要求：
1. 输出结构：
   **诗句**（引用原文，带标点）
   出处：作者 · 篇名
   赏析：2~4 句白话赏析（说清这句好在哪、意境/情感/人生况味）
2. 诗句要真的美或真的有力量，冷门佳句优先。
3. 中文输出，150~250 字。
4. 只输出上述结构，不要前言结语。
5. 飞书 markdown：不要 # 井号标题。"""

WENQING_PROMPT = """请写一段文青风格的句子或短段落（可以是现代诗、散文片段、或一句耐人寻味的话）。

要求：
1. 有画面感或情绪张力，像张爱玲或王小波的笔触：清醒、克制、有余味。
2. 不要鸡汤、不要口号、不要网络流行语。
3. 中文输出，80~150 字。
4. 只输出内容，不要前言结语。
5. 飞书 markdown：不要 # 井号标题。"""


def _get_webhook():
    wh = os.environ.get("POEM_WEBHOOK", "").strip()
    if wh:
        return wh
    try:
        if os.path.exists(WEBHOOK_FILE):
            with open(WEBHOOK_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def main():
    dry = "--dry-run" in sys.argv or os.environ.get("DRY_RUN") == "1"
    is_weekend = datetime.date.today().weekday() >= 5
    prompt = WENQING_PROMPT if is_weekend else POEM_PROMPT
    kind = "wenqing" if is_weekend else "poem"
    print(f"[daily_poem] kind={kind}", flush=True)
    try:
        text = ai_client.chat(prompt, temperature=0.9, max_tokens=1200, thinking=False)
    except Exception as e:
        print(f"[daily_poem] AI 调用失败: {e!r}", flush=True)
        raise SystemExit(1)
    if not text or not text.strip():
        print("[daily_poem] WARN empty AI output", flush=True)
        raise SystemExit(1)
    text = text.strip()

    if dry:
        print(f"[daily_poem][dry-run] kind={kind}\n{text}")
        raise SystemExit(0)

    wh = _get_webhook()
    if not wh:
        print("[daily_poem] WARN no webhook configured, skip", flush=True)
        raise SystemExit(1)
    resp = feishu_notify.send_markdown(TITLE, text, template="purple", webhook=wh)
    code = resp.get("code", resp.get("StatusCode")) if isinstance(resp, dict) else resp
    ok = (code == 0)
    print(f"[daily_poem] push kind={kind} code={code} ok={ok} len={len(text)}", flush=True)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
