"""路径与时间分类工具。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


def sanitize_filename(name: str, max_length: int = 80) -> str:
    """生成安全的文件名片段。"""
    name = (name or "").strip()
    if not name:
        name = "未命名文档"
    # Windows 非法字符
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "未命名文档"
    if len(name) > max_length:
        name = name[:max_length].rstrip(" .")
    return name


def get_iso_week_range(dt: datetime | None = None) -> dict[str, object]:
    """
    按 ISO 8601 计算自然周。

    规则：
    - 一周从【周一】开始，到【周日】结束
    - 第 1 周：包含该年第一个星期四的那一周
      （等价：包含 1 月 4 日的那一周）
    - 跨年时，标签年份用 ISO 周年（iso.year），不一定等于日历年
    """
    now = dt or datetime.now()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Monday=1 ... Sunday=7
    week_start = day - timedelta(days=day.isoweekday() - 1)
    week_end = week_start + timedelta(days=6)
    iso = day.isocalendar()
    return {
        "iso_year": iso.year,
        "iso_week": iso.week,
        "week_label": f"{iso.year}-W{iso.week:02d}",
        "week_start": week_start,
        "week_end": week_end,
        "week_start_str": week_start.strftime("%Y-%m-%d"),
        "week_end_str": week_end.strftime("%Y-%m-%d"),
        "week_range_display": (
            f"{week_start.strftime('%m.%d')}-{week_end.strftime('%m.%d')}"
        ),
    }


def get_time_labels(dt: datetime | None = None) -> dict[str, str]:
    """返回周 / 月 / 季度标签。"""
    now = dt or datetime.now()
    week_info = get_iso_week_range(now)
    year = now.year
    month = now.month
    quarter = (month - 1) // 3 + 1
    return {
        "week": str(week_info["week_label"]),
        "week_start": str(week_info["week_start_str"]),
        "week_end": str(week_info["week_end_str"]),
        "week_range_display": str(week_info["week_range_display"]),
        "month": f"{year}-{month:02d}",
        "quarter": f"{year}-Q{quarter}",
        "year": str(year),
        "date": now.strftime("%Y%m%d"),
        "datetime": now.strftime("%Y%m%d_%H%M%S"),
    }


def build_time_subdirs(
    modes: Iterable[str],
    labels: dict[str, str],
) -> list[tuple[str, Path]]:
    """
    按时间维度构建相对子目录。
    返回 [(mode, relative_subdir), ...]
    目录结构示例：
      by_week/2026-W31/
      by_month/2026-08/
      by_quarter/2026-Q3/
    """
    mode_set = {m.strip().lower() for m in modes if m and m.strip()}
    if not mode_set:
        mode_set = {"month"}

    mapping = {
        "week": ("by_week", labels["week"]),
        "month": ("by_month", labels["month"]),
        "quarter": ("by_quarter", labels["quarter"]),
    }

    results: list[tuple[str, Path]] = []
    for mode in ("week", "month", "quarter"):
        if mode in mode_set:
            folder, label = mapping[mode]
            results.append((mode, Path(folder) / label))
    return results


def ensure_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def unique_path(path: Path) -> Path:
    """若文件已存在则追加序号。"""
    path = Path(path)
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1
