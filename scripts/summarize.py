#!/usr/bin/env python3
"""把 DeepSWE 各 job 的 artifact 汇总成一张表。

用法: python3 scripts/summarize.py artifacts/

输入目录结构（actions/download-artifact 的默认布局）:
    artifacts/deepswe-<task>/jobs/<ts>/<trial>/verifier/reward.json

口径（与官方一致）:
  * 每题一个 binary reward，缺失 reward 视为 0（未跑完/超时/基础设施错误）
  * DeepSWE 分数 = reward 的均值 * 100
  * 另报 fail-to-pass / pass-to-pass 等附加指标的均值（如果 reward.json 里有）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MINI16 = Path(__file__).resolve().parent.parent / "tasks-mini16.txt"


def expected_tasks() -> list[str]:
    if MINI16.exists():
        return [ln.strip() for ln in MINI16.read_text().splitlines() if ln.strip()]
    return []


def find_rewards(root: Path) -> dict[str, dict]:
    """task -> reward dict（同题多条时取最后一个）"""
    out: dict[str, dict] = {}
    for path in sorted(root.rglob("verifier/reward.json")):
        task = None
        for parent in path.parents:
            if parent.name.startswith("deepswe-"):
                task = parent.name[len("deepswe-") :]
                break
        if task is None:
            task = path.parents[1].name
        if "oracle" in str(path):  # oracle 预检不算分
            continue
        try:
            data = json.loads(path.read_text())
        except Exception as exc:  # noqa: BLE001
            print(f"> ⚠️ 无法解析 {path}: {exc}")
            continue
        if isinstance(data, dict) and data:
            out.setdefault(task, {}).update(data)
        elif isinstance(data, (int, float)):
            out.setdefault(task, {})["reward"] = float(data)
    # reward.txt 兜底
    for path in sorted(root.rglob("verifier/reward.txt")):
        if "oracle" in str(path):
            continue
        task = None
        for parent in path.parents:
            if parent.name.startswith("deepswe-"):
                task = parent.name[len("deepswe-") :]
                break
        if task is None or task in out:
            continue
        try:
            out[task] = {"reward": float(path.read_text().strip())}
        except Exception:  # noqa: BLE001
            pass
    return out


def numeric_only(d: dict) -> dict[str, float]:
    return {
        k: float(v)
        for k, v in d.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts")
    tasks = expected_tasks()
    rewards = find_rewards(root)

    if not rewards:
        print("# DeepSWE-mini 评测结果\n\n❌ 没有找到任何 `verifier/reward.json`，所有任务都失败或未运行。\n")
        return 0

    keys: list[str] = []
    for d in rewards.values():
        for k in numeric_only(d):
            if k not in keys:
                keys.append(k)
    if "reward" in keys:
        keys.remove("reward")
    keys = ["reward", *keys]

    rows = []
    for task in tasks or sorted(rewards):
        d = numeric_only(rewards.get(task, {}))
        rows.append((task, d))

    total = len(rows)
    solved = sum(1 for _, d in rows if d.get("reward") == 1)
    score = 100.0 * sum(d.get("reward", 0.0) for _, d in rows) / total if total else 0.0
    missing = [t for t, d in rows if not d]

    print("# DeepSWE-mini 评测结果\n")
    print(f"- 任务数：**{total}**（期望 {len(tasks) or total}）")
    print(f"- 解出（binary reward=1）：**{solved}/{total}**")
    print(f"- **DeepSWE-mini score（reward 均值）：{score:.1f}**")
    for k in keys[1:]:
        avg = 100.0 * sum(d.get(k, 0.0) for _, d in rows) / total if total else 0.0
        print(f"- 均值 {k}：{avg:.1f}")
    if missing:
        print(f"- ⚠️ 缺失/失败（按 0 计）：{', '.join(missing)}")
    print()

    header = "| task | " + " | ".join(keys) + " |"
    print(header)
    print("|" + "---|" * (len(keys) + 1))
    for task, d in rows:
        if not d:
            print(f"| `{task}` | " + " | ".join(["—"] * len(keys)) + " |")
            continue
        cells = []
        for k in keys:
            v = d.get(k)
            cells.append("—" if v is None else (f"{v:.0f}" if k == "reward" else f"{v:.2f}"))
        print(f"| `{task}` | " + " | ".join(cells) + " |")
    print()
    print("> 口径：每任务 1 rollout；缺失 reward 记为 0（超时/基础设施错误计失败）；")
    print("> harness = pier + mini-swe-agent(pinned)；与官方 58.7 对比时须注明自部署 NVFP4 / LLMRouter / 上下文配置差异。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
