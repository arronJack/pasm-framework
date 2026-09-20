"""框架异常定义。

框架层只抛这一类错误，方便应用层统一捕获；引擎内部异常（pasm.*）
一律在后端里被吞掉、降级，不向上污染框架。
"""
from __future__ import annotations


class FrameworkError(Exception):
    """框架层统一异常基类。"""


class SurfaceMissing(FrameworkError):
    """某个框架表面（接口）在运行时找不到实现。

    典型场景：``BaseApplication`` 期望 ``DomainAdapter`` 提供了某个方法，
    但实际注入的是 ``NullDomainAdapter``。用于把"静默降级"变成"明确的红灯"。
    """


class BackendContractBroken(FrameworkError):
    """后端没有实现 ``CognitiveBackend`` 协议要求的成员。

    surface-guard 会专门抓这一类——只要 V1/V2 后端动了契约，
    CI 立刻红，而不是让产品智能体在用户机器上崩。
    """
