# DeepSWE-mini on GitHub Actions

给自部署的 Qwen3.8-Flash-Next（经 LLMRouter 暴露）打 DeepSWE-mini 分数。
**一个 job = 一个任务**，16 个 job 并行（`max-parallel` 控制），绕开 6h/job 上限与 runner 磁盘限制。

## 一、已经本地验证过的部分（不用等到 CI 才发现问题）

| 检查项 | 结果 |
|---|---|
| workflow YAML 可解析 | ✅ 16 任务矩阵 + aggregate job |
| `datacurve-pier==0.3.1` 及依赖全在 PyPI（harbor 0.23 / modal / daytona / litellm） | ✅ 不需要 GitHub 源 |
| pier 的 CLI flag 名（`-p/-a/-m/--ak/--ae/-e/-n/-o/-y/-r/--agent-timeout-multiplier`） | ✅ 对着 0.3.1 源码逐个核对 |
| 官方 pin 的 harness 版本存在 | ✅ `mini-swe-agent==2.3.0`（PyPI 有，最新 2.4.6） |
| 任务集 commit 可复现 | ✅ pin `0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea` |
| LLMRouter `/v1/models` `/v1/chat/completions` `/v1/responses` | ✅ 200 |
| **tool calling（`tools` + `finish_reason=tool_calls`）** | ✅ 返回 `tool_calls:[{function:{name:bash,arguments:...}}]` |
| **多轮 tool 协议**（assistant.tool_calls + `role:"tool"` 回灌） | ✅ 正常出最终答案 |
| streaming（`stream=true`，含 `delta.reasoning`） | ✅ |
| `usage` 字段完整性（`cached_tokens` / `reasoning_tokens`） | ✅ |
| 用户代理：Cloudflare 只拦 `Python-urllib`，httpx / `OpenAI/Python` / litellm 的 UA 都放行 | ✅ mini-swe-agent 走 litellm→httpx，不受影响 |
| 汇总脚本 `scripts/summarize.py` | ✅ 用 16 个假 artifact（含缺失/reward.txt 兜底）跑通 |

## 二、怎么跑起来（需要你的仓库写权限）

```bash
cd deepswe-gha
git init -b main && git add -A && git commit -m "DeepSWE-mini eval on GitHub Actions"
git remote add origin git@github.com:<you>/<repo>.git
git push -u origin main
```

1. 仓库 → Settings → Secrets and variables → Actions → 新建 **`LLMROUTER_API_KEY`**（建议单开一把 key，用量好统计）。
2. Actions → **DeepSWE-mini eval** → Run workflow：
   - `task_set=smoke` + `oracle_first=true`：只跑第一个任务，先验管道（oracle 应 reward=1）→ 再验模型。
   - `task_set=mini16` + `max_parallel=4`：正式跑 16 题。

## 三、输入参数

| 输入 | 默认 | 说明 |
|---|---|---|
| `task_set` | `mini16` | `smoke` 只跑矩阵第一个任务（其余 job 秒退，几乎不耗时） |
| `oracle_first` | `true` | 用参考解跑一遍 oracle，验证 collect hook / 独立 verifier / grader |
| `max_parallel` | `4` | 后端只有 2 卡，超过 4 只会让单任务更慢 |
| `model_name` | `hosted_vllm/qwen3.8-flash-next` | 走 chat/completions；备选 `openai/qwen3.8-flash-next`（走 `/v1/responses`，实测 200） |
| `api_base` | `https://llmrouter.projectk.org/v1` | 必须写在配置里，pier 靠它生成容器 egress 白名单 |
| `mini_swe_agent_version` | `2.3.0` | leaderboard pin 的版本，别改，否则与 58.7 不可比 |
| `agent_timeout_multiplier` | `1.0` | 官方 agent 超时 3h；若大量任务卡超时（自部署比云 API 慢），可设 1.5 并在报数时注明 |

## 四、口径与偏离（报数时必须写清）

- 官方：DeepSWE v1.1 / pier + mini-swe-agent **2.3.0** / `temp=1.0, top_p=0.95, top_k=20` / 256K ctx / 256K 原生窗口。
- 我们：**自部署 NVFP4、经 LLMRouter、服务端 `max-model-len=1000000`（YaRN factor 4）**。YaRN 对短文本有轻微影响，与官方不可直接比。
- 计分：每题 1 rollout；缺失 reward 记 0（超时/基础设施错误记失败）；分数 = reward 均值 ×100。
- 边跑边看：每个 job 的 artifact `deepswe-<task>`；`aggregate` job 会把 16 个结果汇成一张表写进 **Step Summary**。

## 五、失败怎么处理

- 单个任务失败：Actions 里 `Re-run failed jobs`（pier 侧还有 `-r 1` 一次基础设施重试）。
- 想省时间：`pier job resume` 支持断点续跑，但 GHA 是干净 VM，没有持久化；需要续跑就改用 `qwased/deepswe-launcher` 那类带断点的 driver。
- 磁盘不够（`No space left`）：把 `preinstalled-runtimes` 保持 `true`，并确认 `jlumbroso/free-disk-space@v2.0.0` 步骤执行成功（日志里有 "Saved ..." 输出）。

## 六、成本

- public repo：标准 runner 免费不限分钟。
- private repo：免费 2000 min/月；16 job × 最多 3h ≈ 2880 min，超出约 **$23** 封顶。
