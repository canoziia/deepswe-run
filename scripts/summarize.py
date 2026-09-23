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


def _task_from_path(path: Path, known: list[str]) -> str:
    """从 artifact 目录名里找出任务名。

    兼容三种布局：
      artifacts/deepswe-<task>/...          （upload-artifact 的命名）
      artifacts/<task>/...
      artifacts/<run>/<task>/...
    否则退回倒数第二级目录名。
    """
    for parent in path.parents:
        name = parent.name
        if name in known:
            return name
        if name.startswith("deepswe-") and name[len("deepswe-") :] in known:
            return name[len("deepswe-") :]
    for parent in path.parents:
        if parent.name.startswith("deepswe-"):
            return parent.name[len("deepswe-") :]
    return path.parents[1].name


def find_rewards(root: Path) -> dict[str, dict]:
    """task -> reward dict（同题多条时取最后一个）"""
    known = expected_tasks()
    out: dict[str, dict] = {}
    for path in sorted(root.rglob("verifier/reward.json")):
        if "oracle" in str(path):  # oracle 预检不算分
            continue
        task = _task_from_path(path, known)
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
        task = _task_from_path(path, known)
        if task in out:
            continue
        try:
            out[task] = {"reward": float(path.read_text().strip())}
        except Exception:  # noqa: BLE001
            pass
    return out


RATIO_KEYS = ["reward", "f2p", "p2p", "partial"]
COUNT_KEYS = ["f2p_passed", "f2p_total", "p2p_passed", "p2p_total"]

# 这些异常算“模型没做出来”（超时 / 上下文耗尽），按官方 leaderboard 口径计入分母
COUNTED_FAILURES = {
    "AgentTimeoutError",
    "VerifierTimeoutError",
    "ContextWindowExceededError",
    "ContextLengthExceededError",
    "RewardFileNotFoundError",
    "RewardFileEmptyError",
    "VerifierOutputParseError",
}


def find_exceptions(root: Path) -> dict[str, set[str]]:
    """task -> 该题出现过的异常类名集合（从 pier 的 trial result.json 里挖）。"""
    known = expected_tasks()
    out: dict[str, set[str]] = {}
    for path in sorted(root.rglob("result.json")):
        if "oracle" in str(path):
            continue
        try:
            data = json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            continue
        found: set[str] = set()

        def walk(node) -> None:
            if isinstance(node, dict):
                if isinstance(node.get("exception_type"), str):
                    found.add(node["exception_type"])
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(data)
        if found:
            out.setdefault(_task_from_path(path, known), set()).update(found)
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
            if k in RATIO_KEYS and k not in keys:
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

    # 官方 leaderboard 口径：基础设施错误移出分母，超时/上下文耗尽算失败
    exceptions = find_exceptions(root)
    counted, excluded = [], []
    for task, d in rows:
        if d:
            counted.append(d.get("reward", 0.0))
        elif exceptions.get(task) and not (exceptions[task] & COUNTED_FAILURES):
            excluded.append(task)  # 纯基础设施错误，不计入
        else:
            counted.append(0.0)  # 超时/上下文耗尽/无信息：算失败
    score_official = 100.0 * sum(counted) / len(counted) if counted else 0.0

    print("# DeepSWE-mini 评测结果\n")
    print(f"- 任务数：**{total}**（期望 {len(tasks) or total}）")
    print(f"- 解出（binary reward=1）：**{solved}/{total}**")
    print(f"- **DeepSWE-mini score（缺失计 0）：{score:.1f}**")
    print(
        f"- **DeepSWE-mini score（官方口径，基础设施错误移出分母）：{score_official:.1f}**"
        f"（分母 {len(counted)}/{total}）"
    )
    if excluded:
        print(f"- 基础设施错误（已移出分母）：{', '.join(excluded)}")
    for k in keys[1:]:
        avg = 100.0 * sum(d.get(k, 0.0) for _, d in rows) / total if total else 0.0
        print(f"- 均值 {k}：{avg:.1f}")
    counts = {k: 0.0 for k in COUNT_KEYS}
    for _, d in rows:
        for k in COUNT_KEYS:
            if k in d:
                counts[k] += d[k]
    if any(counts.values()):
        print(
            "- 测试用例累计：f2p %g/%g，p2p %g/%g"
            % (
                counts["f2p_passed"],
                counts["f2p_total"],
                counts["p2p_passed"],
                counts["p2p_total"],
            )
        )
    if missing:
        print(f"- ⚠️ 无 reward（按上面的规则处理）：{', '.join(missing)}")
    if exceptions:
        print("\n异常明细：")
        for task in sorted(exceptions):
            print(f"- `{task}`：{', '.join(sorted(exceptions[task]))}")
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
            if v is None:
                cells.append("—")
            elif k == "reward":
                cells.append(f"**{v:.0f}**" if v == 1 else f"{v:.0f}")
            else:
                cells.append(f"{v * 100:.0f}%")
        extra = ""
        if "f2p_total" in d:
            extra = f" {d.get('f2p_passed', 0):g}/{d.get('f2p_total', 0):g}"
        print(f"| `{task}` | " + " | ".join(cells) + " |" + f"{extra} |")
    print()
    print("> 口径：每任务 1 rollout；缺失 reward 记为 0（超时/基础设施错误计失败）；")
    print("> harness = pier + mini-swe-agent(pinned)；与官方 58.7 对比时须注明自部署 NVFP4 / LLMRouter / 上下文配置差异。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
