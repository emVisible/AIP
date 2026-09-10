"""AFL（APA Flow Language）—— Track A 语言层。

定位（冻结）：L3真相源 → 编译向下到 ProcessDef → 引擎一字不动。
本包只做：文本 → AST（parser）→ build_process 可消费的 dict（compiler）。
执行语义归 process.py；动词归 registry；兜底归 code.python。
"""
from .compiler import compile_text, load_afl
from .parser import DslError
from .printer import print_text

__all__ = ["compile_text", "load_afl", "print_text", "DslError"]
