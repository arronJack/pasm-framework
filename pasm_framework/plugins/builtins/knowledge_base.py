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


#: 停用词 —— 检索前先从文本里剔除。
#:
#: 为什么必须剔：这些词**不携带主题信息**，却几乎出现在每个提问里。
#: 实测踩到的两个真缺陷都源于此 ——
#:   ①「积分怎么算」→ 命中**退货**条目：`怎么` 出现在退货条目的**标题**里，
#:      而标题权重是正文的 3 倍，泛疑问词压过了真正的主题材「积分」；
#:   ②「你们老板叫什么」→ 命中自学习沉淀下来的无关问答：`你们`/`什么` 命中。
#: 剔掉之后，查询里剩下的才是"用户到底在问什么"。
#:
#: 注意**不要**把可能属于正文的词放进来（如"说明""介绍""政策"）——
#: 那样会把检索能力一起削掉。
_STOPWORDS: tuple = (
    # 疑问词
    "怎么", "怎样", "怎么样", "如何", "什么", "啥", "为什么", "为何",
    "多少", "多久", "多长时间", "哪里", "哪个", "哪些", "哪种", "几位",
    "是否", "能否", "能不能", "可不可以", "有没有", "是不是",
    # 客套 / 人称 / 语气
    "请问", "麻烦", "帮我", "我想", "我要", "你们", "我们", "咱们", "他们",
    "一下", "一点", "有点",
    # 单字虚词（保守取用：只收几乎不含主题信息的）
    "的", "了", "吗", "呢", "吧", "啊", "呀", "哦", "嗯",
    "是", "有", "我", "你", "他", "她", "它", "们",
    "想", "要", "能", "会", "这", "那", "很", "都", "也", "就", "还", "谁",
)

#: 单字停用词单独拎出来，便于"只在孤立出现时才剔"（见 `_strip_stopwords`）。
_SINGLE_STOPWORDS = frozenset(w for w in _STOPWORDS if len(w) == 1)
_MULTI_STOPWORDS = tuple(w for w in _STOPWORDS if len(w) > 1)


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def _strip_stopwords(text: str) -> str:
    """剔除停用词。

    多字停用词直接删；**单字停用词只在"孤立"时删** ——
    否则会把「会员积分」里的 `会` 删成「员积分」（虽然 bigram 仍能救回"积分"，
    但「退货」这种词一旦被误删就彻底查不到了）。孤立 = 前后不是汉字。
    """
    t = text or ""
    for w in _MULTI_STOPWORDS:
        if w in t:
            t = t.replace(w, " ")
    # 单字：两侧都不是汉字时才剔除（(?![\u4e00-\u9fff]) 保证不在词内部动手）
    t = re.sub(
        r"(?<![\u4e00-\u9fff])([%s])(?![\u4e00-\u9fff])" % "".join(_SINGLE_STOPWORDS),
        " ", t,
    )
    return t


def _tokenize(text: str) -> List[str]:
    """中英文混合的轻量分词：词 + 中文相邻二字（bigram）。

    只产出长度 >= 2 的候选，**不做单字匹配** —— 单字重叠（如"么""你"）
    会造成大量误命中，是客服答非所问的常见根因。
    另外先剔停用词：泛疑问词不携带主题信息，留着只会制造误命中（见 `_STOPWORDS`）。
    """
    t = _strip_stopwords(_norm(text))
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
        # 检索下限：命中分低于此值视为"没命中"。默认 0 表示不启用
        # （保持与早期版本一致的行为）；高精度场景可调高。
        self._min_score: float = float(self.config.get("min_score", 0.0))
        self._lock = threading.RLock()
        self._entries: List[Dict[str, Any]] = []
        self._seq = 0
        # —— 检索加速：倒排索引 + 每条目的分词缓存 ——
        # 不加这两样时，每次 recall 都要对**全库**重新分词（O(n·m)），
        # 资料库一大就明显变慢；索引把每次检索降到只算候选集。
        self._index: Dict[str, set] = {}
        self._index_dirty: bool = True
        self._tokens_cache: Dict[int, set] = {}
        # 已落盘条目数：用于"只追加新增"，避免每次 ingest 全量重写。
        self._persisted: int = 0
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
            self._persisted = len(self._entries)
        except Exception:
            pass

    def _save(self) -> None:
        """全量重写（压缩 / 迁移用）。日常写入请用 :meth:`_append_new`。"""
        p = self._path()
        try:
            tmp = p.with_suffix(".jsonl.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                for e in self._entries:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            os.replace(tmp, p)
            self._persisted = len(self._entries)
        except Exception:
            pass

    def _append_new(self) -> None:
        """只把"尚未落盘的新条目"追加写入。

        旧实现在每次写入时全量重写整个 jsonl —— ingest 十万条就是 O(n²)。
        条目是只追加（append-only）的，因此追加写等价且是 O(新增条数)。
        """
        new = self._entries[self._persisted:]
        if not new:
            return
        try:
            with self._path().open("a", encoding="utf-8") as f:
                for e in new:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            self._persisted = len(self._entries)
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
                self._append_new()
                self._index_dirty = True
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
            self._append_new()
            self._index_dirty = True

    # ---- 索引 ----
    @staticmethod
    def _entry_fields(e: Dict[str, Any]) -> tuple:
        """把条目分词成 ``(title, tags, content)`` 三组 —— 分字段是为了加权。

        为什么必须分字段：不分时"标题命中"和"正文顺带提到"同权，会出现
        「问退货，答运费（因为正文里有一句"退货运费由我方承担"）」这类
        答非所问。标题命中显然更该排前面。
        """
        def tk(v: Any) -> set:
            return set(t for t in _tokenize(str(v or "")) if len(t) >= 2)

        return (tk(e.get("title")), tk(" ".join(e.get("tags", []) or [])),
                tk(e.get("content")))

    def _fields_of(self, pos: int, e: Dict[str, Any]) -> tuple:
        """带缓存的条目分词：同一份资料只分词一次。"""
        cached = self._tokens_cache.get(pos)
        if cached is None:
            cached = self._entry_fields(e)
            self._tokens_cache[pos] = cached
        return cached

    def _ensure_index(self) -> None:
        """惰性重建倒排索引：token → 条目下标集合。

        条目只追加，故下标稳定。索引把检索从"遍历全库"降到"只看候选集"。
        """
        if not self._index_dirty:
            return
        idx: Dict[str, set] = {}
        for pos, e in enumerate(self._entries):
            title, tags, content = self._fields_of(pos, e)
            for t in (title | tags | content):
                idx.setdefault(t, set()).add(pos)
        self._index = idx
        self._index_dirty = False

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
        with self._lock:
            self._ensure_index()
            # 候选集 = 命中任一 query token 的条目（倒排索引给出，无需全库扫描）
            cand: set = set()
            for t in q_tokens:
                posts = self._index.get(t)
                if posts:
                    cand |= posts
            entries = self._entries

        scored = []
        for pos in cand:
            if pos >= len(entries):
                continue
            e = entries[pos]
            title, tags, content = self._fields_of(pos, e)
            n_title = len(q_tokens & title)
            n_tags = len(q_tokens & tags)
            n_content = len(q_tokens & content)
            overlap = n_title + n_tags + n_content
            if overlap == 0:
                continue
            # 分字段加权：标题 3 > 标签 2 > 正文 1。
            overlap_w = n_title * 3.0 + n_tags * 2.0 + n_content * 1.0
            precision = overlap / max(1, len(q_tokens))
            recency = 1.0 / (1.0 + (time.time() - float(e.get("ts", 0))) / (86400 * 30))
            kind_boost = 1.15 if e.get("kind") == "qa" else 1.0
            score = (overlap_w * 2.0 + precision * 2.0) \
                * (0.6 + 0.4 * recency) * kind_boost
            if score < self._min_score:
                continue
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
        # 注意：读路径**不落盘**。hits 只是统计量，为它全量重写 jsonl
        # 会让每次问答都变成 O(n) 磁盘写（旧实现的问题）。
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
