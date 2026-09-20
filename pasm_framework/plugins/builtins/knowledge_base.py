"""knowledge_base —— 站点数据自学资料库插件（零依赖，智能客服核心）。

这是「智能客服能自学、记忆、成长」的关键拼图：
  · **摄取（ingest）**：把站点 FAQ / 文档 / 商品说明变成结构化资料库；
  · **检索（recall）**：在 ``on_retrieve`` 阶段把相关资料注入 ``msg.facts``，
    让回复有依据、不瞎编；
  · **自学习（grow）**：每次高质量问答再沉淀成 QA 对，资料库越用越厚 → 成长。

检索当前用「关键词重叠 + 时效/重要度」打分（零依赖）；后续可平滑替换为向量检索，
对外契约（``recall(query,k) -> [fact]``）不变。
"""
from __future__ import annotations

import json
import os
import re
import time
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core import BasePlugin, Message, PluginContext


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def _tokenize(text: str) -> List[str]:
    """中英文混合的轻量分词：词 + 中文相邻二字（bigram）。

    只产出长度 >= 2 的候选，**不做单字匹配** —— 单字重叠（如"么""你"）
    会造成大量误命中，是客服答非所问的常见根因。
    """
    t = _norm(text)
    t = re.sub(r"[\s\W_]+", " ", t)
    toks: List[str] = []
    for w in t.split(" "):
        if not w:
            continue
        toks.append(w)
        chars = re.findall(r"[\u4e00-\u9fff]", w)
        for i in range(len(chars) - 1):
            toks.append(chars[i] + chars[i + 1])
    return toks


class KnowledgeBasePlugin(BasePlugin):
    """资料库：摄取 → 检索 → 自学习。"""

    name = "knowledge_base"
    version = "0.1.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._kb_dir = self.config.get("kb_dir") or (
            str(Path(os.path.expanduser("~/.pasm_framework/kb")))
        )
        self._auto_learn: bool = bool(self.config.get("auto_learn", True))
        self._min_qa_len: int = int(self.config.get("auto_learn_min_len", 12))
        self._top_k: int = int(self.config.get("top_k", 5))
        self._lock = threading.RLock()
        self._entries: List[Dict[str, Any]] = []
        self._seq = 0
        self._ensure_dir()
        self._load()

    # ---- 持久化 ----
    def _ensure_dir(self) -> None:
        try:
            Path(self._kb_dir).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _path(self) -> Path:
        return Path(self._kb_dir) / "kb.jsonl"

    def _load(self) -> None:
        p = self._path()
        if not p.exists():
            return
        try:
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        self._entries.append(json.loads(line))
                    except Exception:
                        pass
            self._seq = max([e.get("id", 0) for e in self._entries], default=0)
        except Exception:
            pass

    def _save(self) -> None:
        p = self._path()
        try:
            tmp = p.with_suffix(".jsonl.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                for e in self._entries:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            os.replace(tmp, p)
        except Exception:
            pass

    # ---- 摄取 ----
    def ingest(self, items: List[Dict[str, Any]]) -> int:
        """摄取资料库条目。每条：``{title, content, source, tags}``。

        返回新增条数。这是"站点数据自然形成资料库"的入口——
        应用启动时把 FAQ / 帮助文档喂进来即可。
        """
        added = 0
        with self._lock:
            for it in (items or []):
                title = str(it.get("title") or it.get("content") or "")[:120]
                content = str(it.get("content") or it.get("title") or "")
                if not content.strip():
                    continue
                self._seq += 1
                self._entries.append({
                    "id": self._seq,
                    "title": title,
                    "content": content,
                    "source": str(it.get("source") or "ingest"),
                    "tags": list(it.get("tags") or []),
                    "kind": "doc",
                    "ts": time.time(),
                    "hits": 0,
                })
                added += 1
            if added:
                self._save()
        return added

    def ingest_qa(self, question: str, answer: str, source: str = "self-learn") -> None:
        """沉淀一条 QA 对（自学习 / 成长）。"""
        q, a = _norm(question), _norm(answer)
        if not q or not a:
            return
        with self._lock:
            self._seq += 1
            self._entries.append({
                "id": self._seq,
                "title": q[:120],
                "content": "问：%s\n答：%s" % (question, answer),
                "source": source,
                "tags": _tokenize(question)[:8],
                "kind": "qa",
                "ts": time.time(),
                "hits": 0,
            })
            self._save()

    # ---- 检索 ----
    def recall(self, query: str, k: int = 0) -> List[Dict[str, Any]]:
        k = k or self._top_k
        q = _norm(query)
        if not q:
            return []
        # 只用长度>=2 的词 / 中文 bigram 做重叠匹配（不做单字匹配），
        # 避免「么」「你」这类高频单字造成大量误命中。
        q_tokens = set(t for t in _tokenize(query) if len(t) >= 2)
        if not q_tokens:
            return []
        scored = []
        with self._lock:
            entries = list(self._entries)
        for e in entries:
            blob = " ".join([str(e.get("title", "")), str(e.get("content", "")),
                             " ".join(e.get("tags", []))])
            b_tokens = set(t for t in _tokenize(blob) if len(t) >= 2)
            overlap = len(q_tokens & b_tokens)
            if overlap == 0:
                continue
            precision = overlap / max(1, len(q_tokens))
            recency = 1.0 / (1.0 + (time.time() - float(e.get("ts", 0))) / (86400 * 30))
            kind_boost = 1.15 if e.get("kind") == "qa" else 1.0
            score = (overlap * 3.0 + precision * 2.0) \
                * (0.6 + 0.4 * recency) * kind_boost
            scored.append((score, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, e in scored[:k]:
            out.append({
                "title": e.get("title"),
                "brief": (e.get("content") or "")[:300],
                "tags": e.get("tags", []),
                "source": "knowledge_base:%s" % e.get("source"),
                "kb_id": e.get("id"),
                "kind": e.get("kind", "doc"),
                "sal": round(score, 3),
                "score": round(score, 3),
            })
            e["hits"] = e.get("hits", 0) + 1
        if scored:
            with self._lock:
                self._save()
        return out

    # ---- Hook ----
    def on_retrieve(self, ctx: PluginContext) -> None:
        msg: Message = ctx.message
        hits = self.recall(msg.text, k=self._top_k)
        for h in hits:
            msg.add_fact(h)

    def on_learn(self, ctx: PluginContext) -> None:
        if not self._auto_learn:
            return
        msg: Message = ctx.message
        if msg.error or not msg.reply:
            return
        # 「答不上来」的兜底回复不沉淀，避免污染资料库（见 BaseApplication 设置的标记）。
        if msg.meta.get("no_answer"):
            return
        # 只沉淀"有实质内容"的问答，避免噪声污染资料库。
        if len(_norm(msg.reply)) < self._min_qa_len:
            return
        # 已有正式资料（doc）覆盖则不重复沉淀；高置信命中也跳过。
        existing = self.recall(msg.text, k=3)
        if any(e.get("kind") == "doc" and e.get("score", 0) >= 1.0 for e in existing):
            return
        if existing and max(e.get("score", 0) for e in existing) >= 6.0:
            return
        self.ingest_qa(msg.text, msg.reply)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            docs = sum(1 for e in self._entries if e.get("kind") == "doc")
            qas = sum(1 for e in self._entries if e.get("kind") == "qa")
            return {"total": len(self._entries), "docs": docs, "qa": qas}
