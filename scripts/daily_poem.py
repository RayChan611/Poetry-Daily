#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日诗词 -> 飞书群机器人

2026-11-17 重写。原版让模型自己"挑一句古诗"，模型会编作者和篇名（同目录 README
有记录：一批 150 条里 109 条作者是假的）。现在改成：

  诗句 = 从本地语料库按序取（gushiwen.cn 检索来的真句，作者出处可查）
  AI   = 只写赏析，不碰诗句本身

语料：同目录 quotes.json / quotes.N.json，与「此刻」共用同一批。
去重：共用 saohua_history.json，取句时跳过已推送过的句子，也就不会和「此刻」撞车。
指针：poem_state.json {"index": N}，指向合并语料里的序号，顺序往前走不回环。

周末不再单独推「文青句子」——那部分是模型现写的，真伪无从核。现在每天都推真句。

用法:
  python3 daily_poem.py            # 生成并推送
  python3 daily_poem.py --dry-run  # 只生成不推送、不落盘

webhook 复用「此刻」的 .saohua_webhook，可用 POEM_WEBHOOK 覆盖。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai_client
import feishu_notify

BASE = os.path.dirname(os.path.abspath(__file__))
WEBHOOK_FILE = os.path.join(BASE, ".saohua_webhook")
STATE_FILE = os.path.join(BASE, "poem_state.json")
HISTORY_FILE = os.path.join(BASE, "saohua_history.json")

TITLE = "每日诗词"

APPRECIATE_PROMPT = """下面是一句真实的古诗文名句，作者与篇名均已确证，不要改动它：

「{text}」
——{author}《{book}》

请写一段 150~250 字的白话赏析，说清这句好在哪：意象、情绪、或者人生况味。

要求：
1. 只谈这一句，不要引申到别的诗，不要复述作者生平。
2. 不要"这句诗的意思是"这类套话开场，直接进入赏析。
3. 不要用 # 井号标题，飞书卡片渲染不可控。
4. 中文输出，只输出赏析正文，不要前言结语。"""


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


def _batch_files():
    """与 saohua.py 相同的发现规则：quotes.json 起，quotes.N 遇缺号停，上限 50。"""
    files = []
    first = os.path.join(BASE, "quotes.json")
    if not os.path.exists(first):
        return files
    files.append(first)
    for i in range(2, 51):
        p = os.path.join(BASE, "quotes.%d.json" % i)
        if not os.path.exists(p):
            break
        files.append(p)
    return files


def _corpus():
    out = []
    for f in _batch_files():
        try:
            with open(f, "r", encoding="utf-8") as fh:
                out += json.load(fh)
        except Exception as e:
            print("[daily_poem] 读取语料失败 %s: %r" % (f, e), flush=True)
    return out


def _pushed_texts():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return {h.get("text", "").strip() for h in json.load(f)}
    except Exception:
        return set()


def _load_index():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return int(json.load(f).get("index", 0))
    except Exception:
        return 0


def _save_index(i):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"index": i}, f, ensure_ascii=False)


def _mark_pushed(q):
    hist = []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        pass
    hist.append({"text": q["text"], "author": q["author"], "book": q["book"]})
    if len(hist) > 2000:
        hist = hist[-2000:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False)


def _pick():
    """按序取下一句没推过的。全部推过则返回 None——宁可当天不推，也不重复。"""
    corpus = _corpus()
    if not corpus:
        return None, 0
    seen = _pushed_texts()
    idx = _load_index() % len(corpus)
    for step in range(len(corpus)):
        i = (idx + step) % len(corpus)
        q = corpus[i]
        text = (q.get("text") or "").strip()
        if not text or text in seen:
            continue
        return q, (i + 1) % len(corpus)
    return None, idx


def main():
    dry = "--dry-run" in sys.argv or os.environ.get("DRY_RUN") == "1"

    q, next_idx = _pick()
    if not q:
        print("[daily_poem] 语料全推过了，跳过本次推送", flush=True)
        raise SystemExit(1)

    text = q["text"].strip()
    author = q.get("author", "").strip()
    book = q.get("book", "").strip()
    print("[daily_poem] 取句 %s《%s》%s" % (author, book, text), flush=True)

    prompt = APPRECIATE_PROMPT.format(text=text, author=author, book=book)
    try:
        note = ai_client.chat(prompt, temperature=0.9, max_tokens=1200, thinking=False)
    except Exception as e:
        print("[daily_poem] AI 调用失败: %r" % (e,), flush=True)
        raise SystemExit(1)
    if not note or not note.strip():
        print("[daily_poem] WARN 赏析为空，不推半成品", flush=True)
        raise SystemExit(1)
    note = note.strip()

    md = "**%s**\n\n——%s《%s》\n\n%s" % (text, author, book, note)

    if dry:
        print("[daily_poem][dry-run] 下次指针 %d" % next_idx, flush=True)
        print(md, flush=True)
        raise SystemExit(0)

    wh = _get_webhook()
    if not wh:
        print("[daily_poem] WARN 没有 webhook 配置，跳过", flush=True)
        raise SystemExit(1)

    resp = feishu_notify.send_markdown(TITLE, md, template="purple", webhook=wh)
    code = resp.get("code", resp.get("StatusCode")) if isinstance(resp, dict) else resp
    ok = (code == 0)
    print("[daily_poem] push code=%s ok=%s len=%d" % (code, ok, len(md)), flush=True)

    if ok:
        _save_index(next_idx)
        _mark_pushed(q)
    else:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
