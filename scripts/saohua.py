#!/usr/bin/env python3
"""每两小时推一条书摘/金句 + AI 引读 到飞书「此刻」群。

方向（2026-08-03 起）：各类书里被多人标记、有深度的句子，附一句 AI 引读。
内容取自本地真实语料库，按批次(quotes.json / quotes.2.json / ...)顺序轮播：
  - 单批次内不重复（顺序推进）
  - 播完一批自动切下一批
  - 全部播完则回到第 1 批（记日志），等待补充新批次
引读由 AI 生成（极简单句，非名言、不编造出处）；生成失败则只发原句。

用法：
  python3 saohua.py            # 正常推送
  python3 saohua.py --dry-run  # 只打印将推送内容，不发飞书（用于验证）
"""
import os
import sys
import json
import random
import fcntl

import ai_client
import feishu_notify

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE, "quotes_state.json")
WEBHOOK_FILE = os.path.join(BASE, ".saohua_webhook")
HISTORY_FILE = os.path.join(BASE, "saohua_history.json")
LOCK_FILE = os.path.join(BASE, ".saohua.lock")
TITLE = "此刻"
RECENT = 1000  # 2026-09-03 扩窗口到 1000，避免 231 条语料回环失忆 + 接纳旧 history 种回

FALLBACK = [
    {"text": "人是为活着本身而活着，而不是为了活着之外的任何事物所活着。", "author": "余华", "book": "活着"},
    {"text": "围在城里的人想逃出来，城外的人想冲进去。", "author": "钱钟书", "book": "围城"},
    {"text": "所有成年人都曾经是小孩，只是他们忘了。", "author": "圣埃克苏佩里", "book": "小王子"},
    {"text": "凡杀不死我的，必使我更强大。", "author": "尼采", "book": "偶像的黄昏"},
    {"text": "世界上最宽阔的是海洋，比海洋更宽阔的是天空，比天空更宽阔的是人的胸怀。", "author": "雨果", "book": "悲惨世界"},
    {"text": "一个人并不是生来要给打败的。你尽可以把他消灭掉，可就是打不败他。", "author": "海明威", "book": "老人与海"},
]


def _batch_files():
    files = []
    primary = os.path.join(BASE, "quotes.json")
    if os.path.exists(primary):
        files.append(primary)
    n = 2
    while n <= 50:
        p = os.path.join(BASE, f"quotes.{n}.json")
        if os.path.exists(p):
            files.append(p)
            n += 1
        else:
            break
    return files


def _load_batch(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return data
    except Exception as e:
        print(f"[saohua] batch load error {path}: {e!r}")
    return []


def _load_state():
    st = {"batch": 0, "index": 0}
    try:
        if os.path.exists(STATE_FILE):
            d = json.load(open(STATE_FILE, encoding="utf-8"))
            st["batch"] = int(d.get("batch", 0))
            st["index"] = int(d.get("index", 0))
    except Exception:
        pass
    return st


def _save_state(st):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f)
    except Exception:
        pass


def _load_history():
    try:
        if os.path.exists(HISTORY_FILE):
            data = json.load(open(HISTORY_FILE, encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_history(hist):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(hist, f)
    except Exception:
        pass


def _pick(persist=True):
    files = _batch_files()
    if not files:
        return random.choice(FALLBACK), {"batch": 0, "index": 0}
    history = _load_history()
    recent_texts = {h.get("text") for h in history[-RECENT:]}
    st = _load_state()
    if st["batch"] >= len(files):
        st["batch"] = 0
        st["index"] = 0
    # 顺序轮播 + 最近去重：跳过最近 RECENT 条内已推送过的句子
    q = None
    chosen_use = 0
    wrapped = False
    for _ in range(400):
        batch = _load_batch(files[st["batch"]])
        if not batch:  # 当前批次文件异常，跳下一批
            st["batch"] = (st["batch"] + 1) % len(files)
            st["index"] = 0
            continue
        use = st["index"] % len(batch)
        cand = batch[use]
        # 推进
        st["index"] = st["index"] + 1
        if st["index"] >= len(batch):
            st["index"] = 0
            st["batch"] = st["batch"] + 1
            if st["batch"] >= len(files):
                st["batch"] = 0
                wrapped = True
        recently_pushed = cand.get("text") in recent_texts
        if not recently_pushed:
            q = cand
            chosen_use = use
            if wrapped:
                print("[saohua] 所有批次已播完，回到第 1 批（如需换新内容请补充 quotes.N.json）")
            break
        # 最近推过则继续取下一条（顺延，不会重复）
    if q is None:  # 极端兜底（不应发生）
        q = random.choice(FALLBACK)
        chosen_use = st["index"]
    if persist:  # dry-run 不落盘，避免测试导致指针漂移
        _save_state(st)
    return q, {"batch": st["batch"], "index": chosen_use}


def _webhook():
    wh = os.environ.get("SOAOHUA_WEBHOOK", "").strip()
    if wh:
        return wh
    try:
        if os.path.exists(WEBHOOK_FILE):
            with open(WEBHOOK_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def _build_quote_md(q):
    text = (q.get("text") or "").strip()
    author = (q.get("author") or "").strip()
    book = (q.get("book") or "").strip()
    md = text
    if author:
        md += "\n\n—— " + author
        if book:
            md += "《" + book + "》"
    return md


def _gen_intro(quote):
    try:
        prompt = (
            "为下面这句话写一句极简的引读/解读，帮助读者停顿一下：\n"
            f"「{quote}」\n\n"
            "要求：不超过 28 字，点到为止；不要重复原句；不要加引号；不要 emoji；"
            "像朋友随口点破的一句，而非名言。"
        )
        intro = ai_client.chat(
            prompt,
            system="你是写书摘引读的人，话少而准，不煽情。",
            temperature=0.85,
            max_tokens=60,
            thinking=False,
        )
        intro = (intro or "").strip().strip("「」『』\"'").strip()
        if intro:
            return intro
    except Exception as e:
        print(f"[saohua] 引读生成失败: {e!r}")
    return ""


if __name__ == "__main__":
    # 并发锁：避免多次触发（含手动+定时重叠）导致同一句被推送两次
    try:
        _lock = open(LOCK_FILE, "w")
        fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[saohua] another instance is running, exit")
        raise SystemExit(0)

    DRY = "--dry-run" in sys.argv
    q, loc = _pick(persist=not DRY)
    md_quote = _build_quote_md(q)
    wh = _webhook()
    intro = _gen_intro(q.get("text", ""))

    md = (intro + "\n\n" + md_quote) if intro else md_quote

    if DRY:
        print(f"[saohua][dry-run] batch={loc['batch']} index={loc['index']} intro_set={bool(intro)}")
        print("[saohua][dry-run] md =\n" + md)
        print(f"[saohua][dry-run] webhook_set={bool(wh)}")
        raise SystemExit(0)

    if not wh:
        print("[saohua] WARN no webhook configured, skip")
        raise SystemExit(1)

    # 共享层 feishu_notify 已处理限流退避/永久错误快失败，此处无需重复重试
    resp = feishu_notify.send_markdown(TITLE, md, template="purple", webhook=wh)
    code = resp.get("code", resp.get("StatusCode")) if isinstance(resp, dict) else resp
    ok = (code == 0)
    print(f"[saohua] push code={code} ok={ok} text_len={len(md)}")
    if not ok and code is not None:
        print(f"[saohua] WARN push failed resp={resp}")
    # 仅推送成功才记入最近历史（去重依据）；失败则保留索引位置、下次重试
    if ok:
        hist = _load_history()
        hist.append({"text": q.get("text", ""), "author": q.get("author", ""), "book": q.get("book", "")})
        if len(hist) > RECENT * 2:
            hist = hist[-RECENT * 2:]
        _save_history(hist)
