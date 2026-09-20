"""BaseSkill —— 技能包的代码化底座。

为什么把"技能"也收进框架
------------------------
当前 ``pasm-agents/skill/`` 下的技能（companion / npc / tutor / verify）是
``SKILL.*.md`` + ``*.body.md`` 的**纯文档**结构：名字、触发词、正文全靠人读 Markdown。
这导致：① 触发逻辑无法被 surface-guard 自动验证；② 同一能力在文档里写一套、
在代码里又写一套，容易漂移。

``BaseSkill`` 把技能变成**代码对象**：

  - ``SkillManifest`` 声明 name / version / triggers / description（替代 SKILL.md 的元信息）；
  - ``BaseSkill.run(context) -> str`` 是技能执行体（替代散落的 body.md 解释）；
  - ``to_manifest_dict()`` 仍能导出成旧 ``SKILL.md`` 兼容结构，保证老加载器不破。

这样"技能触发 + 执行"可被自动测、可被 CI 守护，是又一个 V1↔V2 不该动的稳定面。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass
class SkillManifest:
    """技能的机器可读元信息（对应旧 SKILL.md 的 front-matter）。"""

    name: str
    version: str = "0.1.0"
    description: str = ""
    triggers: Tuple[str, ...] = ()     # 触发词（句首匹配，与 Capability 同源规则）
    entry: str = ""                    # 入口（模块路径或命令），旧格式兼容
    extra: Dict[str, Any] = field(default_factory=dict)


class BaseSkill(ABC):
    """技能包代码化底座。

    子类实现：
      - :meth:`manifest`  —— 返回 ``SkillManifest``；
      - :meth:`run`       —— 给定上下文执行技能，返回结果文本。
    """

    @abstractmethod
    def manifest(self) -> SkillManifest:
        """技能元信息。"""

    @abstractmethod
    def run(self, context: Dict[str, Any]) -> str:
        """执行技能。``context`` 至少含 ``text``（用户输入）与 ``app``（调用方应用）。"""

    # ---- 兼容旧 SKILL.md 格式的导出 --------------------------
    def to_manifest_dict(self) -> Dict[str, Any]:
        """导出成旧 ``SKILL.md`` 兼容的 dict（front-matter + 占位 body 指引）。

        旧加载器只读 front-matter 时不受影响；正文由 ``run`` 在运行时生成，
        不再依赖静态 body.md。
        """
        m = self.manifest()
        return {
            "name": m.name,
            "version": m.version,
            "description": m.description,
            "triggers": list(m.triggers),
            "entry": m.entry or f"{type(self).__module__}:{type(self).__name__}",
            "kind": "code-skill",       # 标记这是代码技能，区别于旧 markdown 技能
            "extra": dict(m.extra),
        }

    def matches(self, text: str, head_chars: int = 12) -> bool:
        """按触发词做句首匹配（与 Capability 同源规则）。"""
        t = (text or "").strip()
        if not t:
            return False
        span = t[:head_chars]
        return any(k and k in span for k in self.manifest().triggers)
