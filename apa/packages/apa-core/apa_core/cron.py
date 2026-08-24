"""apa-core: Cron 表达式解析（设计文档 §13.1 apa-scheduler）。

标准 5 字段（分钟级）：
    分 时 日 月 周      字段值：* | */n | a-b | a,b,c | 单值
纯 stdlib 实现，供 Scheduler 做到期判断（不做下一次运行预测）。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import FrozenSet

FIELD_RANGES = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day": (1, 31),
    "month": (1, 12),
    "dow": (0, 6),          # 0=周一（Python weekday()），与 cron 惯例 0=周日不同，
}                            # 此处以 Python 语义为准并在文档标注


class CronError(ValueError):
    pass


def _parse_field(expr: str, lo: int, hi: int, field: str) -> FrozenSet[int]:
    values: set = set()
    for part in expr.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"{field}: empty item in {expr!r}")
        step = 1
        if "/" in part:
            part, _, step_s = part.partition("/")
            if not re.fullmatch(r"\d+", step_s) or int(step_s) == 0:
                raise CronError(f"{field}: bad step {step_s!r}")
            step = int(step_s)
            if part == "*":
                lo_, hi_ = lo, hi
            else:
                base_lo, sep, base_hi = part.partition("-")
                if not re.fullmatch(r"\d+", base_lo):
                    raise CronError(f"{field}: bad range {part!r}")
                lo_ = int(base_lo)
                hi_ = int(base_hi) if sep else hi
        elif part == "*":
            lo_, hi_ = lo, hi
        elif "-" in part and not part.lstrip("-").isdigit():
            a, _, b = part.partition("-")
            if not (re.fullmatch(r"\d+", a) and re.fullmatch(r"\d+", b)):
                raise CronError(f"{field}: bad range {part!r}")
            lo_, hi_, step = int(a), int(b), 1
        else:
            if not re.fullmatch(r"\d+", part):
                raise CronError(f"{field}: bad value {part!r}")
            lo_, hi_, step = int(part), int(part), 1
        if not (lo <= lo_ <= hi and lo <= hi_ <= hi):
            raise CronError(f"{field}: {lo_}-{hi_} out of range [{lo},{hi}]")
        if lo_ > hi_:
            raise CronError(f"{field}: inverted range {lo_}-{hi_}")
        values.update(range(lo_, hi_ + 1, step))
    return frozenset(values)


class CronExpr:
    """解析后的 cron 表达式。matches(dt) 判断给定时刻是否触发。"""

    def __init__(self, expr: str) -> None:
        parts = expr.split()
        if len(parts) != 5:
            raise CronError(f"cron expects 5 fields, got {len(parts)}: {expr!r}")
        self.expr = expr
        parsed = {}
        for name, raw in zip(("minute", "hour", "day", "month", "dow"), parts):
            lo, hi = FIELD_RANGES[name]
            parsed[name] = _parse_field(raw, lo, hi, name)
        self.minute: FrozenSet[int] = parsed["minute"]
        self.hour: FrozenSet[int] = parsed["hour"]
        self.day: FrozenSet[int] = parsed["day"]
        self.month: FrozenSet[int] = parsed["month"]
        self.dow: FrozenSet[int] = parsed["dow"]

    def matches(self, dt: datetime) -> bool:
        """日/月/周同时给出限制时按 OR 语义（POSIX cron：任一命中即触发）。"""
        if dt.minute not in self.minute or dt.hour not in self.hour:
            return False
        if dt.month not in self.month:
            return False
        day_ok = dt.day in self.day
        dow_ok = dt.weekday() in self.dow
        day_limited = "*" not in self.expr.split()[2] or False
        dow_limited = "*" not in self.expr.split()[4] or False
        # POSIX：dom 与 dow 均受限时取并集；仅一个受限时取交集（即该字段）
        if day_limited and dow_limited:
            return day_ok or dow_ok
        return day_ok and dow_ok

    def matches_ms(self, epoch_ms: int) -> bool:
        return self.matches(datetime.fromtimestamp(epoch_ms / 1000))

    def __repr__(self) -> str:
        return f"CronExpr({self.expr!r})"


def is_due(expr: str, epoch_ms: int) -> bool:
    """便捷函数：epoch 毫秒时刻是否命中 cron。"""
    return CronExpr(expr).matches(datetime.fromtimestamp(epoch_ms / 1000))

def next_after(expr: str, from_dt: Optional[datetime] = None,
               *, max_scan_days: int = 366 * 5) -> datetime:
    """下一次触发时刻（分钟精度，严格晚于 from_dt）。

    扫描上限 max_scan_days 天；超限抛 CronError（永无命中属配置错误）。
    快进优化：月/小时不满足时整段跳跃，最坏仍 O(每日分钟数×天数)。
    """
    base = (from_dt or datetime.now()).replace(second=0, microsecond=0)
    cron = CronExpr(expr)

    from datetime import timedelta

    cur = base + timedelta(minutes=1)
    limit = cur + timedelta(days=max_scan_days)
    while cur < limit:
        if cron.matches(cur):
            return cur
        if cur.month not in cron.month:
            # 跳到下月 1 日零分
            nxt_month = (cur.replace(day=1, hour=0, minute=0) +
                         timedelta(days=32)).replace(day=1, hour=0, minute=0)
            cur = nxt_month
            continue
        if cur.hour not in cron.hour:
            cur = (cur + timedelta(hours=1)).replace(minute=0)
            continue
        cur += timedelta(minutes=1)
    raise CronError(f"no matching time within {max_scan_days} days: {expr!r}")
