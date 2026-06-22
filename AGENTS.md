# 全局规则

## 配置修改必须验证（关键）

- **改任何软件配置后必须验证是否正确**，包括但不限于：OpenCode+OMO、Hermes-Agent、KiloCode、系统 cron、Git hooks 等
- **验证方法**：改完配置后**必须立即运行** `python3 ~/.config/opencode/scripts/validate-all-configs.py`，通过后再同步
- **校验脚本覆盖**：Ghost provider、白名单缺失、model/fallback 重复、model.fallback 与 fallback_providers 不一致、YAML 语法错误、auth.json 有 key 但未登记的 provider
- **验证失败则禁止同步推送**，必须修到全 PASS
- **已有案例**：误删 `output` 字段导致 OpenCode 无法启动、cron 升级脚本 CRLF 换行符导致执行失败、plugin 字段重复导致 OMO 被禁用
- **已有案例**：`disabled_providers` 含不存在的 provider 名导致 OpenCode 计数错乱、本应禁用的 Provider 又显示出来
- **已有案例**：`target_ratio` 缩进错误导致 Hermes config.yaml 解析失败→fallback 到默认配置→所有自定义 fallback 被忽略
- **已有案例**：`fallback_providers` 缩进错误导致 Hermes 静默降级

## 禁止操作（关键）

- **禁止添加用户未明确要求的新模型**：不自行判断"某个模型可能可用"就往 provider 白名单里加，必须等用户明确确认
- **禁止模型残留**：将某模型替换为同系列新版本时，必须从同一 provider 的白名单中**删除旧模型**。如 `glm-5.1 → glm-latest`、`qwen3.6-plus → qwen3.7-max`、`nemotron-3-super → nemotron-3-ultra`、`minimax-m2.7 → minimax-m3`，不能新旧并存。**此规则跨所有配置文件和所有 Agent 工具统一执行**。
- **禁止未联网查证**：修改模型配置前必须联网查询官方文档确认模型是否真实可用，严禁凭记忆或猜测添加模型
- **已有案例**：`kimi-k2.7-code` 未经验证加入 volcengine 白名单导致 Coding Plan 报不兼容、`glm-5.1` 和 `glm-latest` 共存违反替换规则

## Provider 白名单一致性校验（同步前强制）

- **每次改完 provider 配置后同步前**，必须运行以下校验确认无 ghost provider：
  ```python
  disabled = set(config["disabled_providers"])
  valid = set(config["provider"].keys())
  ghost = disabled - valid  # disabled 中有但 provider 中不存在的
  if ghost: 立即清理，禁止带着 ghost 同步
  ```
- **禁止**：`disabled_providers` 含不存在的 provider 名

## 修改范围纪律（关键）

- **只修改用户明确要求修改的内容。其他一律不动。**
- 禁止"改进"、"重构"、"清理"、"优化"或"修复"用户未提及的内容——无论问题看起来多明显。
- 禁止悄悄修复范围外的内容——发现真正问题先问。
- **治标更要治本**：修复 bug 时追根因，不是给症状打补丁。修完要问"同类问题还会不会在别处发生？"
- 禁止触碰相邻代码、附近函数、相关文件或导入，除非用户请求直接需要

## 发现错误自动修复流程（关键）

- **发现问题别问用户**：调用不同 Review AGENT 分析错误原因
- **综合分析评审结果确定根因后自动修复**
- **修复完再用不同 Review AGENT 验证是否符合预期**
- **只有多种不同模型都判断错误原因不明确时才问用户**

## 网页 JS 无法渲染时的模型验证（关键）

- **优先使用 API 文档**：用 `context7_query-docs` 或 `webfetch` 查官方 API 参考（如 `https://api-docs.deepseek.com`）
- **搜索引擎找文本版**：用搜索引擎搜 `provider名 + supported models + coding plan` 找纯文本说明页面
- **实在找不到 → 必须问用户确认**：严禁自行添加未经验证的模型

## 模型配置原则

- **思考程度变体只保留最高思考程度**（如 DeepSeek 的 `reasoningEffort: max`，不保留 low/medium）
- **其它限制性越少越好**：能不配置 `input` 就不配（OpenCode 自动从 API 读取），`output` 如果 OpenCode 要求必须配则配
- **免费端点优先**：所有 fallback 链中，免费端点（NIM、OpenRouter free、Cloudflare、Modal、ModelScope）排在付费端点前面
- **弱模型不进评审链**：新增模型时，如果其在 Arena 或 Artificial Analysis 排行榜上排名低于当前已有模型列表中排名最低的模型，则不添加（排行榜随时间变化，不设固定门槛）

## 上下文窗口 Fallback 方向（关键）

> ⚠️ **核心原则：小窗口模型 fallback 到大窗口模型没问题，大窗口 fallback 到小窗口会触发上下文压缩（context compression），严重降智。**

- **kimi-k2.6 上下文仅 262K，只用于评审（ReviewKimi），禁止作为任何 Agent 工具主模型的 fallback**
- **从所有 Agent 工具的主模型 fallback 链中移除 kimi-k2.6**
- **主模型选择策略**：对于任意 Agent 工具，如果当前主模型的能力评分与 kimi-k2.6 相近（同属一个档次），**优先将主模型切换为 kimi-k2.6**。原因：262K 模型报错后可 fallback 到 1M 模型（安全）；反之 1M 模型 fallback 到 262K 模型会直接触发压缩导致严重降智
- **评审 Agent 中保留 kimi-k2.6**：ReviewKimi 以 kimi-k2.6 为主模型（评审 prompt 通常较短，不触发压缩）
- **主模型切换规则**：通过对话切换主模型时，把之前的主模型放回 fallback 列表，把新的主模型从 fallback 列表剪切到主模型位置——严禁重复

## Provider 优先级规则

所有 Agent 工具的 fallback 链都应遵循以下优先级顺序：

| 优先级 | 类型 | 示例 |
|---|---|---|
| 1 | 免费端点 | NVIDIA NIM、OpenRouter free、OpenCode Zen free、Cloudflare Workers AI、ModelScope |
| 2 | 单家 CodingPlan/TokenPlan | GLM CodingPlan、Kimi CodingPlan、MiMo TokenPlan |
| 3 | 聚合平台 CodingPlan/TokenPlan | 火山方舟、腾讯云、阿里云百炼、百度千帆 |
| 4 | 便宜按量付费 | DeepSeek 官方、MiMo 官方 |
| 5 | 中等按量付费 | 国产模型比 DeepSeek/MiMo 贵但比国际四巨头便宜（火山方舟按量、阿里云按量等） |
| 6 | 贵按量付费 | Grok、Gemini、Claude、GPT 等国际四巨头按量付费 |

> ⚠️ **每个定价档次内按具体价格相对排序**，贵的排后面。
> ⚠️ **评审 Agent 内部也遵循此优先级**：每个 ReviewXXX 的 model 字段应放优先级最高的可用端点，fallback_models 按优先级递减排列。

## Codex 与 OpenCode 双向评审调用（关键）

### ReviewGPT 定位

- ReviewGPT 使用 Codex ChatGPT Plan 的 `gpt-5.5`，但不是 OpenCode provider 或 OMO category。
- 运行前必须先执行 `codex login status`。标准只读非交互命令为：
  ```bash
  codex exec -c 'approval_policy="never"' -m gpt-5.5 -s read-only \
    --skip-git-repo-check -o review-gpt.txt "评审提示"
  ```
- 显示 `Not logged in` 时应报告“未登录/缺少认证”；只有运行日志明确返回 HTTP 401 才能报告 401，并须区分 `Missing bearer`、token 过期等具体原因。参数解析失败、超时和余额不足也必须分别准确报告。
- 禁止复制或同步 `~/.codex/auth.json` token。ReviewGPT 不可用时按成本优先级逐个调用其它模型家族补票，不降低 M=2。
- 主模型属于 GPT/OpenAI 家族时必须排除 ReviewGPT；GPT-5.4 与 GPT-5.5 不能作为两张独立票。

### Hermes/Codex 调用 OpenCode

- 判断 OpenCode 不存在前，必须依次检查 `command -v opencode`、`~/.opencode/bin/opencode` 和 `find /root -name opencode -type f -not -path '*/.git/*'`；PATH 中找不到命令不等于未安装。
- 调用 OpenCode 非交互评审时，必须传入唯一临时 `--title`。结束后使用该次运行的精确 OpenCode session ID，把 `session.title` 改为 `评审任务-任务简称-Review角色-结果-时间`，并通过 `opencode db` SELECT 回读验证。
- PASS、FAIL、待核实、超时、余额不足和其它调用失败都必须改名，禁止遗留会挤占交互会话列表的临时标题。
- 不同 Review 角色若实际 fallback 到同一模型家族，只能合计一票；必须继续调用其它家族补足 M=2。

## ⚠️ 【最高优先级】修改必须评审（不可跳过）

### 代码修改评审

- **任何代码修改前必须调用多模型评审，无例外**
- **Git pre-commit hook 会硬阻断未评审的提交，没有后门**
- **禁止 `SKIP_REVIEW=1` 或 `ALLOW_UNREVIEWED_EDIT=1` 绕过评审**
- **强制排除规则**：主模型是哪家的，**严禁**调用同家 ReviewXXX 评审——同一个模型写代码再自己评审自己，纯浪费 Token 且无交叉验证意义
- 评审流程：改代码 → `task(category="ReviewXXX")` 调用不同模型评审 → M≥2 通过 → `mark-review-passed` → commit
- **无论用户是否在当条消息中强调"禁止跳过评审"，都必须走评审流程**
- 主模型是 MiMo 则优先用 ReviewGLM + ReviewKimi，缺票时按 ReviewMinimax → ReviewDeepseek → ReviewQwen 逐个补审（排除 ReviewMimo）
- 主模型是 DeepSeek 则优先用 ReviewGLM + ReviewKimi，缺票时按 ReviewMinimax → ReviewMimo → ReviewQwen 逐个补审（排除 ReviewDeepseek）

### 文档修改评审

- **修改文档（AGENTS.md 等）也需多模型评审**，禁止跳过评审直接同步
- 评审流程同代码：改文档 → `task(category="ReviewXXX")` 调用 2+ 不同模型评审 → 全通过 → 多端同步
- **未评审的文档修改禁止同步到远程和多端**

## 文件编辑安全（关键）

- **修改文件时必须使用 `edit`（局部替换）。禁止使用 `write` 全量覆写，除非文件是全新的且不存在。**
- 编辑任何文件前，必须先用 `read` 工具读取该文件。禁止编辑未读取过的文件。
- 使用 `edit` 时，`oldString` 必须包含足够的上下文以唯一定位目标。禁止使用可能多次出现的单行匹配。
- 编辑后，必须通过回读修改区域或运行 `lsp_diagnostics` 验证文件完整性。
- 大文件（超过 300 行）应使用多次小的定向编辑，而非一次大的改动。
- **禁止截断或遗漏现有代码。** 如果不确定完整内容，再次读取文件后再编辑。

## 实时验证（关键）

- **写代码前必须联网搜索（web search、librarian、context7 等）验证事实、API、库用法和文档。禁止仅凭记忆或训练数据。**
- 使用任何库、框架或 API 时——即使是你"知道"的——必须先查阅最新文档。API 会变更、包会废弃、签名会演进。
- 对事实不确定时（版本号、方法签名、配置选项、废弃状态），将记忆视为过期数据，直到在线验证。
- 这尤其适用于：npm/pip/cargo 包、云服务商 API、框架版本、CLI 参数和配置格式。

## Provider 与模型配置（关键）

- **在 `opencode.json` 或 `oh-my-openagent.json` 中添加或更新任何 provider 时，必须：**
  1. **验证平台确实提供该模型**——搜索 provider 官方文档/公告。禁止假设所有 provider 遵循 OpenAI 兼容的模型命名规范，即使 base URL 以 `/v1` 结尾。
  2. **验证精确的模型 ID**——搜索 provider 的 API 文档获取正确的模型名称参数值。禁止猜测或从其他 provider 推断。
  3. **验证上下文窗口、最大输出和输入限制**——查阅官方规格。禁止编造这些数字。
  4. **检查模型变体（thinking/reasoning 级别）**——如果模型支持 `reasoning_effort` 或 `thinking` 变体（`low`/`medium`/`high`/`max`/`xhigh`），删除所有较低变体条目，在 models 列表和 whitelist 中只保留最高变体。禁止仅记录映射关系——必须从配置文件中物理删除较低变体。
  5. **提交前验证**——通过查阅 provider 当前的 API 文档确认模型 ID 确实可用，而非过期的缓存数据。
- **尚未支持某模型的平台不应配置该模型。** 移除或回退到平台支持的模型。
- **禁止为 provider 配置其未公开文档化的模型。**

## 修改范围纪律（关键）

- **只修改用户明确要求修改的内容。其他一律不动。**
- 禁止"改进"、"重构"、"清理"、"优化"或"修复"用户未提及的内容——无论问题看起来多明显。
- 禁止触碰相邻代码、附近函数、相关文件或导入，除非用户请求直接需要。
- 禁止添加注释、重新格式化、重命名变量或重组代码，除非明确要求。
- 如果发现范围外的真实问题，先提出警告。禁止悄悄修复。
- 不确定某修改是否在范围内时——不在范围内。先询问。

## 仓库目录整洁（关键）

- **新增或修改文件前，必须先判断文件应该放在哪个目录。** 代码、脚本、文档、测试、部署配置、临时产物应放到对应目录（如 `app/`、`scripts/`、`docs/`、`tests/`、`deploy/` 等），不得为了省事把新文件直接放在仓库根目录。
- 仓库根目录只允许放真正属于全项目级别的入口文件、核心配置、README/AGENTS、依赖清单等。调试脚本、一次性诊断文件、导出文件、日志、截图、图片、私密材料和构建产物不得放在根目录；用完即删，需保留则移动到合适目录并写明用途。

## GitHub Copilot 全局规则

- **Copilot 只保留免费模型**，不付费订阅 Copilot Pro/Pro+
- **白名单只保留 Arena + Artificial Analysis 综合排名靠前的 2 个免费模型**（2026-06 验证）：
  - `copilot.claude-haiku-4-5`（Arena #101, AI Index 37）
  - `copilot.gpt-5-mini`（Arena #65, AI Index 33）
- **用途**：仅作为小 AGENT（sisyphus-junior）的 fallback 模型，不作为主模型或大 AGENT 模型
- **定期验证**：每季度检查 Arena 和 Artificial Analysis 排名，如有更优免费模型则替换

## 语言

- 所有回复使用中文。

## 模型准入门槛（关键）

给各 AGENT 工具（OpenCode+OMO、KiloCode、Hermes-Agent、OpenClaw、MiMo-Code 等）配置添加新模型时，**不得添加比已有模型列表中排行最低的模型排名更低的新模型**。

排行参考：
- https://artificialanalysis.ai/leaderboards/models?status=all
- https://arena.ai/leaderboard/text

操作流程：
1. 查看新模型在上述排行榜的排名
2. 确认当前配置中排名最低的模型
3. 如果新模型排名低于最低门槛，不添加

## 语法校验与测试（关键）

- **每次修改完代码后，必须进行严格的语法校验**（如运行 linter、类型检查、语法分析等），确保代码无语法错误、无类型错误、符合项目代码规范，不得提交或部署未通过语法校验的代码。
- **推送代码前，必须确保所有单元测试通过**。如果有测试框架，任何会导致测试失败的改动都不应推送。

## 免费端点变化每日检查（关键）

- **涉及修改 Agent 工具配置的会话**，每天第一次对话时必须联网查询所有免费端点对强模型的支持变化
- 免费端点包括但不限于：NVIDIA NIM、Cloudflare Workers AI、OpenRouter Free、OpenCode Zen Free、ModelScope、Modal、GitHub Copilot Free
- 发现新强模型→评估是否加入 Agent fallback；发现模型下架/退休→同步清理所有配置
- 此检查仅针对"修改 Agent 工具配置"的会话，普通编码会话无需执行

## 多端体验一致性（关键）

- **所有设备的 OpenCode+OMO 使用体验应尽可能一致**：配置文件（opencode.json、oh-my-openagent.json、AGENTS.md、auth.json）在所有设备上保持同步
- **全局要求必须同步**：AGENTS.md 中的全局要求修改后，立即同步到所有设备家目录 + GitHub 仓库
- **仓库内配置必须对齐**：涉及 AI 调用的 git 仓库内如果有自己的 opencode.json/oh-my-openagent.json，必须与全局配置保持一致
- **同步全局配置后必须同步所有项目目录**：如果某个项目目录有独立的 opencode.json，同步全局时必须一并更新，避免出现 TUI 中已禁用的 Provider 又出现
- **同步全局 AGENTS.md 后必须同步所有项目目录**：`/root/crawl_cars`、`/root/.hermes` 等项目目录如果有自己的 AGENTS.md，用全局最新版本覆盖。同理 E:\Codes 下的所有 repo 也要同步
- **项目级 AGENTS.md 不能直接覆盖**：先读取目标文件内容，有项目特有规则的部分保留，冲突处以全局为准或询问用户，无冲突处合并
- **Windows 通过 SSH 运行 OpenCode 时，项目路径会被记录为 Windows 格式**：如 `O:/codes/billiards_tqt` 而非 Linux 路径，这些会话在 Linux 端 OpenCode 重启时会导致 Drizzle 查询错误。解决方案：定期清理 OpenCode 数据库中的无效路径会话，但不能直接删除整个数据库（违反"只改用户要求改的"规则）

## 全局要求同步检查（关键）

- **每个 git 仓库内的 OpenCode 会话，每天首次启动时必须检查远程 AGENTS.md 是否有更新**：对比本地与 GitHub `Fatty911/Personal_commonly_used/ai_tools/opencode/AGENTS.md` 的版本
- **会话运行期间每半小时检查一次**：`git pull` 或 `webfetch` 远程 AGENTS.md，发现更新立即读取并合并到当前会话上下文
- **发现远程规则变更立即应用**：不等到下次重启，当前会话内立即按照最新规则行事
- **不只检查全局仓库**：当前 git 项目如果有自己的远程仓库（如 `Fatty911/crawl_cars`），也要同步检查其 AGENTS.md 是否有更新

## 提交推送与运行监测（关键）

- **任务完成后必须自动提交并推送**：在确保代码质量、语法校验和必要测试通过后，必须自动 `commit` 并 `push`，不能只把改动留在本地。若项目要求 Pull Request，推送后创建或更新 PR，并在 CI 通过后继续合并；除非用户明确要求暂停或只做本地改动。
- **推送、热更新、重启或部署容器后必须监测运行情况**：必须继续检查 CI/容器状态、健康接口和关键日志，确认服务持续运行后再交付结论。
- **推送代码前，必须确保所有单元测试通过**：如果有测试框架，任何会导致测试失败的改动都不应推送。
- **推送后必须监控 CI 测试**：提交推送完必须至少监控到测试成功；如果时间窗口允许修改的工作流运行，还应监控修改的工作流运行结果是否符合预期。

## 多模型共识评审机制（关键）

> ⚠️ **【强制规则】所有代码修改前必须触发多模型共识评审，无例外。**
> 
> 这是解决"不同模型改出来的代码各不一样、花式报错"问题的核心机制。

### 核心原则

- **任何代码修改都必经共识评审**（除纯查询/读取操作外）
- **通过并行启动 N 个 category 评审任务实现多模型评审**——每个 category 绑定独立模型
- **N 选 M 通过制 + 懒启动**：首批恰好并行 N=2 个不同模型家族，M=2；两者都 PASS 才停止，否则按成本优先级逐个启动后续 Review，达到 2 张有效 PASS 后立即停止
- **流程**：排除主模型同家 Review → 并行启动 N 个 → M≥2 立即继续 → 不足则逐加 → 标记 → 同步推送
- 评审 Agent **只有读权限**（不可 edit/bash），不会修改代码

### ⚠️ 技术说明

`task()` 的 `subagent_type` 是固定枚举，不支持自定义名。但 `category` 支持 OMO 配置中任意名称，**经实测 `task(category="ReviewGLM")` 可用**。自定义 ReviewXXX 通过 category 机制运行，非 subagent_type。

### 共识评审工作流程

```
主控 agent（sisyphus）收到修改请求
  │
  ├── 第一步：确定当前主模型，排除对应的 Review category
  │   例如主模型是 volcengine-coding/glm-5.1 → 排除 ReviewGLM
  │   从剩余 Review category 中按成本优先级选 2 个并行启动
  │
  ├── 第二步：Sisyphus 先启动前 N 个评审任务（默认 N=2）
  │   task(category="ReviewDeepseek", prompt="...", run_in_background=true)
  │   task(category="ReviewKimi", prompt="...", run_in_background=true)
  │   task(category="ReviewMimo", prompt="...", run_in_background=true)
  │   ⚠️ 先启动 N 个，全部通过则不启动第 N+1 个；不达标再逐个启动后续 Review
  │
  ├── 第三步：监控评审状态（每 3 分钟检查一次）
  │   - 如果 N 个全部通过 → 不启动第 N+1 个，立即继续任务（省 Token）
  │   - 如果 N 个中达到 M 个通过 → 立即继续任务
  │   - 如果 N 个中通过不足 M 个 → 启动第 N+1、N+2…逐一启动
  │   - 主 Agent 每 3 分钟检查一次未返回结果的评审状态
  │
  ├── 第四步：收集评审结果
  │   - 后续返回的评审结果如果提出问题 → 主 AGENT 必须查看并改进
  │   - 后续返回的评审结果没提出问题 → 忽略，提升效率
  │
  └── 第五步：标记评审通过 → 同步到全端 → 推送
```

### 评审 Category 模型覆盖

每个 review category 绑定独立模型，确保多模型交叉验证：

| Category | 主模型 | Fallback | 定位 |
|---|---|---|---|
| **ReviewGLM** | volcengine-coding/glm-5.1 | nvidia-glm-5.1, modal-glm-5.1, modelscope-glm-5 | GLM-5.1 评审 |
| **ReviewDeepseek** | deepseek/deepseek-v4-pro | volcengine-deepseek | DeepSeek V4 评审 |
| **ReviewKimi** | volcengine-coding/kimi-k2.6 | nvidia-kimi, cloudflare-kimi, openrouter-kimi-free, cf-kimi-k2.7 | Kimi K2.6 评审 |
| **ReviewQwen** | alibaba/qwen3.7-max | — | Qwen 3.7 评审 |
| **ReviewMimo** | mimo-tokenplan/mimo-v2.5-pro | — | MiMo V2.5 评审 |
| **ReviewMinimax** | nvidia/nvidia-minimax-m3 | — | MiniMax M3 评审 |
| **ReviewGrok** | proxy_xai/grok-4.3 | — | Grok 4.3 兜底评审 |

> ⚠️ **设计原则**：每个 ReviewXXX 只包含 XXX 家的模型。优先调用 ReviewGLM/ReviewKimi/ReviewDeepseek，ReviewGrok 作为兜底。

### 评审 Provider 优先级（每个 ReviewXXX 内部）

| 优先级 | 类型 | 示例 |
|---|---|---|
| 1 | 免费端点 | nvidia, OpenCode Zen, OpenRouter free, Cloudflare, Modal, ModelScope |
| 2 | 单家 Plan | GLM CodingPlan, Kimi CodingPlan, MiMo TokenPlan |
| 3 | 聚合平台 Plan | 火山方舟, 腾讯云, 阿里云百炼, 百度千帆 |
| 4 | 单家按量付费 | DeepSeek 官方, GLM 按量, Kimi 按量, MiMo 按量 |
| 5 | 聚合平台按量付费 | 火山方舟按量, 阿里云按量 |

### 评审模型选择规则（强制）

**评审必须使用和写代码的主模型不同的模型，禁止用同模型评审自己的代码。**

选择逻辑：
1. **优先选有免费或 Plan 端点的 Review**（ReviewGLM、ReviewKimi、ReviewDeepseek、ReviewMinimax）
2. 只有前面不够时，才补纯按量付费的 Review；便宜的 ReviewMimo 必须早于 ReviewQwen
3. 都不可用时，用 ReviewGrok 兜底

| 主模型 | 排除 | 评审优先选择 |
|---|---|---|
| DeepSeek V4 Pro | ReviewDeepseek | ReviewGLM + ReviewKimi + ReviewMinimax + ReviewMimo + ReviewQwen |
| GLM-5.1 | ReviewGLM | ReviewKimi + ReviewMinimax + ReviewDeepseek + ReviewMimo + ReviewQwen |
| Kimi K2.6 | ReviewKimi | ReviewGLM + ReviewMinimax + ReviewDeepseek + ReviewMimo + ReviewQwen |
| Qwen 3.7 Max | ReviewQwen | ReviewGLM + ReviewKimi + ReviewMinimax + ReviewDeepseek + ReviewMimo |
| MiMo V2.5 Pro | ReviewMimo | ReviewGLM + ReviewKimi + ReviewMinimax + ReviewDeepseek + ReviewQwen |
| MiniMax M3 | ReviewMinimax | ReviewGLM + ReviewKimi + ReviewDeepseek + ReviewMimo + ReviewQwen |
| 其它模型 | 无 | ReviewGLM + ReviewKimi + ReviewMinimax + ReviewDeepseek + ReviewMimo + ReviewQwen |

> 任何 Review 不可用时，用 ReviewGrok（proxy_xai/grok-4.3）兜底补审。
> 不同 Review 角色若实际 fallback 到同一模型家族，只能合计一票；必须继续调用其它家族补足 M=2。

**禁止跳过评审直接修改代码。**

### 默认评审策略

> **用户未明确指定评审参数时，自动采用以下默认策略：**
> - **N=2**（首批恰好并行启动 2 个不同家族的 Review）
> - **M=2**（首批两票都 PASS 才放行）
> - 首批不足 2 张 PASS 时，按免费端点 → Plan → 便宜按量 → 中等按量 → 贵按量的顺序逐个补审；MiMo 按量必须早于 Qwen 按量
> - 无需再次询问用户，直接执行懒启动评审
>
> ⚠️ **服务器资源限制**：当前生产服务器为 2核4G，首批只允许 2 个 Oracle 并行运行。

### 评审结果模型标注（强制）

- **评审 Oracle 必须在结果第一行注明所使用的模型名称**，格式：`模型：xxx`
- prompt 中加入：`请在评审结果第一行注明你所使用的模型名称（格式："模型：xxx"）。`
- 如果模型无法确定自身名称，则注明 fallback 链中该序号对应的预期模型
- **评审结果不得匿名，必须可追溯到具体模型**
- 汇总评审结果时，必须展示每个评审对应的模型名称

### Git Pre-commit Hook 强制评审（底层强制）

> **除了提示词层面的规则，Git 层面也强制要求评审：**

**Hook 位置**: `C:\Users\Administrator\.git-hooks\pre-commit`

**工作机制**：
1. 每次 `git commit` 前，hook 检查是否有代码修改（排除 `.md`/`.txt`/`.json` 纯文档）
2. 如果有代码修改，要求先通过多模型评审
3. 评审通过后，调用 `~/.git-hooks/mark-review-passed` 创建临时标记文件（有效期 5 分钟）
4. 标记文件存在时，允许提交

**跳过方式**（仅紧急情况）：
```bash
SKIP_REVIEW=1 git commit -m "emergency fix"
```

**评审通过后必须执行**：
```bash
~/.git-hooks/mark-review-passed review-glm.txt review-kimi.txt review-deepseek.txt
```

> ⚠️ **marker 脚本必须接收评审任务的实际输出文件**，不能让模型自己编摘要。pre-commit hook 会验证标记文件包含真实评审内容，否则拒绝提交。

> ⚠️ **这是底层强制机制，即使模型忘记提示词规则，Git 也会阻止未评审的代码提交。**

**适用范围**：
- **Windows (E:\Codes\)**: AI_XR_Relay_familyai, aider, Auto_add_notes_to_WeChat_group_members, AutoBuild_OpenWrt_for_XiaoMi_R4, Badminton-court-management-system, billiards_tqt, crawl_cars, LibreChat, lobe-chat, opencode-stock, Personal_commonly_used, tabby, zbpack_tmp
- **Windows (C:\Users\)**: Personal_commonly_used, hermes-agent
- **racknerd**: hermes-agent, AutoBuild_OpenWrt, crawl_cars, LibreChat, lobe-chat, Badminton-court, opencode-stock, /root 主 repo
- **jstq**: AutoBuild_OpenWrt, billiards_tqt
- **dmit**: 无 repo，仅安装 mark-review-passed 到 PATH

### Git Pre-push Hook 强制单元测试（底层强制）

> **除了评审，Git 层面也强制要求单元测试通过：**

**Hook 位置**: `C:\Users\Administrator\.git-hooks\pre-push`

**工作机制**：
1. 每次 `git push` 前，hook 检测项目类型（Node.js/Python/Go/Java）
2. 自动运行对应的完整测试套件（`npm test` / `pytest` / `go test` / `mvn test` / `gradlew test`）
3. 测试全部通过才允许推送
4. 测试失败则拒绝推送

**支持的项目类型**：
- **Node.js**: `npm test`（检测 `package.json` 中的 test 脚本）
- **Python**: `pytest`（检测 `pytest.ini` / `pyproject.toml` / `setup.py`）
- **Go**: `go test ./...`（检测 `go.mod`）
- **Java Maven**: `mvn test`（检测 `pom.xml`）
- **Java Gradle**: `./gradlew test`（检测 `build.gradle`）

**跳过方式**（仅紧急情况）：
```bash
SKIP_TESTS=1 git push
```

### Git Hooks 文件清单

| Hook | 触发时机 | 检查内容 | 跳过方式 |
|------|----------|----------|----------|
| **pre-commit** | `git commit` | 多模型评审 + 快速测试 | `SKIP_REVIEW=1` |
| **pre-push** | `git push` | 完整单元测试 | `SKIP_TESTS=1` |

> ⚠️ **这是底层强制机制，即使模型忘记提示词规则，Git 也会阻止未评审、未测试的代码提交和推送。**

## 代码级限制（程序强制）

> 以下限制尽量使用 Git hooks 和 OMO 运行包补丁实现，不能把普通提示词当成硬约束。

### 当前真实生效的硬防线

| 防线 | 位置 | 强制内容 |
|------|------|---------|
| **OMO edit/write/multiedit 评审拦截** | `C:\Users\Administrator\node_modules\oh-my-openagent\dist\index.js` 本地补丁 | 代码文件修改前必须存在 10 分钟内的 `/tmp/.review_passed_*` 标记；`.md/.txt/.json` 豁免 |
| **runtime_fallback 静默成功检测** | `oh-my-openagent` 本地补丁 + `oh-my-openagent.json` | DeepSeek 类 provider 如果 `finish=stop` 但无可见输出/0 output token，则转成 retryable failure 进入 fallback |
| **pre-commit** | `C:\Users\Administrator\.git-hooks\pre-commit` | 代码提交前必须存在 5 分钟内的评审标记 |
| **pre-push** | `C:\Users\Administrator\.git-hooks\pre-push` | 推送前运行项目测试 |

### 评审强制机制（edit/write 前硬阻断）

代码文件修改前必须先完成多模型评审，并执行：

```bash
~/.git-hooks/mark-review-passed
```

当前本机 OMO 运行包已补丁化：`write` / `edit` / `multiedit` 修改代码文件时，如果 10 分钟内没有 `.review_passed_*` 标记，工具调用会直接失败。此限制用于防止 MiMo 等模型忘记或忽略 AGENTS.md。

**重要限制**：这是本机 npm 包补丁，不是上游 OMO 官方能力。升级或重装 `oh-my-openagent` 后必须重新检查/重打补丁；否则 edit 层硬阻断会退化为只有 Git pre-commit 阻断。

### DeepSeek 静默截断处理

DeepSeek 官方 API 便宜，继续使用；但如果它返回 `finish=stop` 且无可见输出或 output token 为 0，不得视为成功。当前 `runtime_fallback.silent_success_detection` 已启用，命中后会构造 `SilentCompletionError`，让 OMO fallback/retry 接管。

### 辅助脚本

| 脚本 | 位置 | 用途 |
|------|------|------|
| **pre-edit-guard.sh** | `~/.config/opencode/hooks/` | 外部脚本版编辑检查；仅在被显式调用时生效，不能假设 OMO 官方会自动执行 |
| **config-sync-validator.sh** | `~/.config/opencode/hooks/` | opencode.json/kilo.json/omo.json 配置同步校验 |
| **validate-model-whitelist.sh** | `~/.config/opencode/hooks/` | Provider whitelist 与 models 定义一致性校验 |
| **pre-save-validator.sh** | `~/.config/opencode/hooks/` | JSON/YAML/Python 保存前语法自动校验 |
| **post-edit-diagnostics.sh** | `~/.config/opencode/hooks/` | 编辑后运行 LSP 诊断（TS/JS/Python/Go/Shell） |
| **code-pattern-guard.py** | `~/.config/opencode/hooks/` | 禁止 `as any`、`@ts-ignore`、`@ts-expect-error`、空 catch 块、console.log 残留 |

### Git Hooks 集成

所有上述代码级检查已集成到 Git pre-commit hook 中：

```
pre-commit hook 检查流程:
  1. 多模型评审检查（必须）
  2. 代码模式校验 (code-pattern-guard.py)（警告，不阻断）
  3. 配置同步校验 (config-sync-validator.sh)
  4. 模型白名单校验 (validate-model-whitelist.sh)
  5. 快速测试检查
```

跳过方式：
- `SKIP_REVIEW=1 git commit` — 跳过所有检查
- `SKIP_CONFIG_SYNC=1 git commit` — 仅跳过配置同步检查蛎

## 总结

- edit > write（已有文件，始终如此）🔒 程序级强制
- 先读后改（无例外）🔒 程序级强制
- 改后验证（始终如此）🔒 程序级强制
- 写代码前联网验证（禁止凭记忆）
- 只改用户让改的（禁止擅自修改）
- 回复使用中文（始终如此）
- 语法校验后才可提交（始终如此）🔒 程序级强制
- 测试通过后才可推送（始终如此）🔒 程序级强制
- 代码修改前必须多模型共识评审（无例外）🔒 程序级强制
- 禁止 `as any` / `@ts-ignore` / 空 catch 🔒 程序级强制
- Provider 模型配置一致性 🔒 程序级强制
- 配置跨文件同步 🔒 程序级强制
- Git pre-commit hook 底层强制评审（无法跳过）
- Git pre-push hook 底层强制单元测试（无法跳过）

## 配置同步（关键）

只要涉及到配置模型，以下所有位置必须同步改写，无一例外：

> ⚠️ **盘符规则**：Windows10 和 Windows11 双系统，各自启动后自己的系统盘都是 C:，另一个系统盘都是 D:。同步时始终用 C: → D:（当前系统推送到另一系统），无需关心当前是哪个系统。
>
> ⚠️ **使用习惯**：用户习惯右键点击开始菜单运行终端，终端默认运行在用户家目录（`C:\Users\Administrator`）。因此用户可能在任意一个 Windows 系统的 Administrator 目录下运行 OpenCode、配置 OpenCode+OMO。配置文件实际位置取决于当前启动的系统盘符。

1. **本机 opencode 配置**: `C:\Users\Administrator\.config\opencode\opencode.json`
2. **本机 OMO 插件配置**: `C:\Users\Administrator\.config\opencode\oh-my-openagent.json`
3. **本机 auth 配置**: `C:\Users\Administrator\.local\share\opencode\auth.json`
4. **另一系统 opencode 配置**: `D:\Users\Administrator\.config\opencode\opencode.json`
5. **另一系统 OMO 插件配置**: `D:\Users\Administrator\.config\opencode\oh-my-openagent.json`
6. **另一系统 auth 配置**: `D:\Users\Administrator\.local\share\opencode\auth.json`
7. **本机 KiloCode 配置**: `C:\Users\Administrator\AppData\Roaming\kilo\kilo.json`
8. **GitHub 所有涉及 AI 调用的仓库**:
   - `Fatty911/Personal_commonly_used/ai_tools/opencode/`
   - `Fatty911/Personal_commonly_used/ai_tools/KiloCode/`
   - `Fatty911/hermes-agent`
9. **远程服务器 root@racknerd.jiucai.eu.org**:
   - `/root/.config/opencode/opencode.json`
   - `/root/.config/opencode/oh-my-openagent.json`
   - `/root/.local/share/opencode/auth.json`
   - `/root/.hermes/config.yaml`
   - `/root/.hermes/auth.json`
10. **远程服务器 root@jstq.com.cn**:
    - `/root/.config/opencode/opencode.json`
    - `/root/.config/opencode/oh-my-openagent.json`
    - `/root/.local/share/opencode/auth.json`
11. **远程服务器 root@dmit.jiucai.eu.org**:
    - `/root/.config/opencode/opencode.json`
    - `/root/.config/opencode/oh-my-openagent.json`
    - `/root/.local/share/opencode/auth.json`

改写时统一遵循以下原则：
- 只保留最新代模型（如 DeepSeek V4、Kimi K2.6、GLM-5.1、Qwen 3.7）
- 变体只保留最高思考程度
- 免费优先，付费辅助
- 各 Provider 按用户指定规则精简白名单

## ⚠️ plugin 字段跨端差异（关键）

- **Windows**：需要 `plugin: ["oh-my-openagent@latest"]` 手动声明（npm 自动检测不生效）
- **Linux**（racknerd/jstq/dmit）：npm 自动检测 + 手动声明**都用 `oh-my-openagent@latest`** 格式，两者一致不会重复
- **同步后无需特殊处理**：`oh-my-openagent@latest` 在 Windows 和 Linux 端通用，不再需要同步后清空 plugin 字段
- **禁止**：使用 `oh-my-openagent`（不带 `@latest`），会导致 Linux 端 OMO 重复注入被禁用

## 已知 Bug 与解决方案

### 自动升级脚本分离

OpenCode 和 Hermes-Agent 的自动升级脚本分开管理，互不影响：

| 脚本 | 位置 | 升级内容 | cron |
|---|---|---|---|
| **auto-upgrade-all.sh** | `/root/.config/opencode/scripts/` | OpenCode + OMO 插件 | `0 0,10,20 * * *` |
| **auto-upgrade-hermes.sh** | `/root/.hermes/` | Hermes-Agent + Gateway | `0 0,10,20 * * *` |

- 删除 Hermes-Agent 不会影响 OpenCode 升级
- 日志分别存储在各自目录下
- 脚本已同步到 racknerd 和 jstq

### 1. OMO 重复注入被禁用
- **现象**：OpenCode 启动时显示 "Duplicate OMO plugin entries detected"，TUI 只显示 Build 和 Plan
- **根因**：`plugin: ["oh-my-openagent"]` 与 npm 自动检测的 `oh-my-openagent@latest` 字符串不同，被当成两个实例
- **解决**：统一使用 `plugin: ["oh-my-openagent@latest"]`，与 npm 检测结果一致
- **已修复**：2026-06-13

### 2. npm 升级 OMO 失败 (ENOTEMPTY)
- **现象**：自动升级脚本执行 `npm install -g oh-my-openagent@latest` 报 `ENOTEMPTY: directory not empty, rename`
- **根因**：npm 升级时旧目录残留 `.oh-my-openagent-*` 临时目录，阻止重命名
- **解决**：在 npm install 前加 `rm -rf /usr/lib/node_modules/.oh-my-openagent-*`
- **已修复**：2026-06-12（racknerd + jstq 升级脚本已更新）

### 3. OpenCode 版本过旧导致 OMO 不识别
- **现象**：racknerd 上 OpenCode 1.14.41，OMO Agent 不显示
- **根因**：自动升级脚本用 `curl https://opencode.ai/install.sh`（URL 多了 `.sh`），404 静默失败
- **解决**：修正为 `curl https://opencode.ai/install`，并加 npm 三重保险
- **已修复**：2026-06-02

### 4. OMO 自定义 category 不生效
- **现象**：`task(category="ReviewGLM")` 报 "Unknown category"
- **根因**：OMO 在 session 启动时缓存 category 列表，session 内修改配置不生效；且旧版本可能不支持自定义 category
- **解决**：改完 OMO 配置后必须重启 OpenCode session；使用 `@latest` 格式确保版本最新
- **已修复**：2026-06-12

### 5. 自定义 subagent_type 不可用
- **现象**：`task(subagent_type="ReviewGLM")` 报错，无法调用自定义 Agent
- **根因**：`task()` 的 `subagent_type` 是固定枚举（oracle, explore, librarian 等），不支持自定义名称
- **解决**：改用 `task(category="quick/deep/ultrabrain")` 实现多模型评审分发
- **已修复**：2026-06-12

### 6. OpenCode SessionRetry 无限重试
- **现象**：provider 月限额后 fallback 不切换，同一模型重试 10+ 次
- **根因**：OpenCode 内部 SessionRetry 对 5xx/403 无限重试（指数退避），OMO fallback 永远等不到介入机会
- **解决**：手动切换主模型；等 OpenCode 官方合并 maxAttempts 配置（GitHub issue #26675）
- **状态**：未解决，OpenCode 已知缺陷

## 2026-06-20 全端配置重整

### 核心事件
- **Hermes-Agent Gemini 404**：`model.default` 为 `openrouter/free`（自动路由），Google BYOK 欠费后 API 返回 404。切为 NIM `z-ai/glm-5.1`，全部 alias 切 NIM，删除所有 `openrouter/free` 自动路由。
- **压缩模型优化**：Hermes-Agent compression 从 `nemotron-3-super`→`nvidia-dsv4-pro` + 5 层 fallback；KiloCode 不支持 fallback，保留 `grok-4.20`。
- **同系列替换**：执行 `nemotron-3-super→ultra`、`minimax-m2.7→m3` 跨所有工具。
- **免费端点扫描**：NIM 新增 `minimax-m3`(1M)、CF 新增 `glm-5.2`(262K)，已加入全 Agent fallback。
- **七牛云 AI**：Provider 已配（5 强模型），`disabled_providers` 中——暂不启用。
- **Modal 免费期结束**：Modal 官方 GLM-5.1 免费端点于 2026-04-30 截止，已禁用（保留 provider 配置）。大 Agent 主模型切 `nvidia-glm-5.1`。
- **qwen3-coder:free 移除**：AI Index 18-25 低于列表中其他模型，不满足质量门。
- **ModelScope 改名**：`modelscope-GLM5`→`modelscope`，删 GLM-5 只保留 MiniMax-M3（避免挤占每日配额）。

### OMO Agent Fallback 最终状态（统一优先级：免费端按上下文 200K→256K→262K→1M，再 Plan→按量→[大]grok）
| Agent 类型 | 模型数 | 来源 | 主模型 |
|---|---|---|---|
| 大 Agent ×7 | 18 | NIM→CF→OR→Zen→MS→Plan→按量→grok | nvidia/glm-5.1 |
| ultrabrain | 16 | k2.6 族优先，无 GLM-5/5.1 | nvidia/kimi-k2.6 |
| 小 Agent ×3 | 20 | copilot 弱模型在最前 | copilot/claude-haiku-4-5 |

### Hermes-Agent
- model.default: `openrouter/free`→`z-ai/glm-5.1`
- model.fallback: NIM(k2.6→dsv4→ultra→minimax-m3)→OR(k2.6)→Plan→按量→grok
- compression: `nvidia-dsv4-pro`+ds官方→vc-dsv4→vc-glm→mimo→grok
- 删除: `summary_model` 遗留键、`openrouter/free` 全部引用、qwen3-coder:free

### KiloCode
- proxy_openrouter whitelist: 2026-06-21 删除已下架的 kimi-k2.6:free；只保留仍由官方 API 列出的免费模型
- NIM whitelist: super→ultra+minimax-m3

### 模型上下文（联网核实）
| 模型 | 上下文 | 备注 |
|---|---|---|
| kimi-k2.6/k2.7-code | 256K | Kimi 官方 |
| GLM-5.1 | 200K | Z.AI 官方 |
| GLM-5.2(vc/七牛) | 1M | Z.AI 官方；CF 临时 262K |
| DeepSeek V4 Pro/Flash | 1M | 官方/HF/NIM |
| Nemotron 3 Ultra | 1M（最大） | NIM 文档 |
| Nemotron 3 Super | 256K 默认/1M 最大 | 已替换为 ultra |
| MiniMax M3 | 1M | MiniMax 官方/NIM/ModelScope 免费 |
| Qwen 3.7 Max | 1M | 阿里云官方 |

### 全端同步 ✅
C: | D: | racknerd | jstq | dmit | GitHub | E:\Codes×12 全部同步

### 新增 Provider：七牛云 AI
- baseURL: `https://api.qnaigc.com/v1`
- 白名单：`glm-5.2`, `kimi-k2.7-code`, `deepseek-v4-pro`, `minimax-m3`, `qwen3.7-max`
- 未开 key → 在 `disabled_providers` 中

### 已知 Bug 与解决方案（新增）

### 7. OpenCode models.json 缓存导致配置不生效
- **现象**：SCP 推送新配置后 `/models` TUI 仍显示旧 Provider、模型上下文仍为旧值
- **根因**：OpenCode 将模型定义缓存在 `~/.cache/opencode/models.json`（2.3MB），改 config 不触发缓存重建
- **解决**：改完配置推送后**必须删除远程服务器上的 models.json 缓存**：`rm -f /root/.cache/opencode/models.json`，下次启动自动重建
- **注意**：Windows 端同理，位于 `C:\Users\<user>\.cache\opencode\models.json`
- **已识别**：2026-06-20

### 8. auth.json 有 key 但未登记的 Provider 仍会在 TUI 显示
- **现象**：`disabled_providers` 和 `provider` 都没有的 provider，但 auth.json 有 key，TUI 仍显示
- **根因**：OpenCode 自动扫描 auth.json，有 key 的 provider 就会出现在模型列表。**且 `disabled_providers` 只对 `provider` 块中存在的 provider 生效——不在 provider 里的 disabled 项被静默忽略**
- **解决**：
  1. auth.json 中有 key 但不用的 provider 必须**同时**加到 `provider`（空 whitelist）和 `disabled_providers`
  2. 只加 `disabled_providers` 不加 `provider` = 无效，OpenCode 仍显示
- **已识别**：2026-06-20，涉及 provider：`qianfan`、`minimax-cn-coding-plan`、`xr_zhipu`、`qwen`

### 9. Copilot 模型退役未同步清理
- **现象**：`copilot.gpt-4.1` 已于 2026-06-01 退役，但仍在白名单中
- **解决**：保留 Copilot 免费最强 2 个模型（`claude-haiku-4-5`、`gpt-5-mini`），删退役模型
- **定期检查**：每季度复查 Copilot Free 模型变化
- **已修复**：2026-06-20

### 10. NIM 429 导致错误归因
- **现象**：NIM API 返回 429 后 fallback 到 kimi-k2.6（256K），提示上下文超限，误以为是 v4-pro 的问题
- **根因**：OpenCode SessionRetry 对 429 无限重试耗尽 fallback 次数，实际调用的是 k2.6 而非 v4-pro
- **排查方法**：先查缓存中的模型上下文 `python3 -c "import json; c=json.load(open('models.json')); ..."` 确认配置无误，再查 fallback 链确认实际调用模型
- **已识别**：2026-06-20

## Provider 白名单强制规则

- **开启 Provider 必须配白名单**：有 auth.json key 的 Provider 必须设 whitelist，不设会导致 TUI 显示全部模型
- **模型 ID 必须查官网确认**：改 models/whitelist 前必须联网查 Provider 官方文档确认模型名称、ID、参数
- **不设白名单的 Provider 要禁用**：避免 provider: auto 时匹配到不该用的端点
- **`disabled_providers` 只对 `provider` 块中存在的 provider 生效**：auth.json 有 key 但 provider 块里没有的 provider，OpenCode 仍会显示——必须同时加入 `provider`（空 whitelist）和 `disabled_providers` 才能完全隐藏
- **proxy_* 端点策略**：OpenRouter、xAI、Google 等共用 API key 的 provider，native 端点禁用（加 provider 空 whitelist + disabled），只启用 proxy_ 版本
- **内置 Provider 也需手动禁用**：OpenCode 自带 google、groq 等内置 provider 定义，即使 auth.json 无 key 也会在 TUI 显示——同样需要加到 provider（空 whitelist）+ disabled_providers

## 本次会话完整改动（2026-06-20）

### 核心事件
- **Hermes-Agent YAML 静默降级**：`target_ratio` 和 `fallback_providers` 缩进错误导致 YAML 解析失败，所有自定义配置被忽略、fallback 到默认。修复后创建 `validate-all-configs.py` 自动校验。
- **TUI `/models` 显示多余 Provider 根因**：3 层问题——① Ghost（disabled 含不存在的 provider）、② auth.json 有 key 但未在 provider 块登记（`disabled_providers` 对此无效）、③ OpenCode 缓存 `models.json` 未清理。
- **OpenRouter/xAI 代理策略**：native `openrouter`/`xai` + provider 空 whitelist → disabled，启用 `proxy_openrouter`/`proxy_xai`。
- **定价档次重新定义**：按量付费拆为三档——便宜（DeepSeek/MiMo 官方）、中等（国产模型，比 DS/MiMo 贵比四巨头便宜）、贵（Grok/Gemini/Claude/GPT）。每档内按具体价格排序。
- **Sisyphus 上下文策略调整**：TUI 默认入口需最长上下文，主模型 `nvidia-deepseek-v4-pro`（NIM 免费/1M），fallback 仅保留 1M 以上模型，移除 nemotron-3-ultra（能力不足）、kimi 系列（262K）、GLM-5.1（200K）、CF/Zen 免费（< 1M）。
- **Ultrabrain Kimi 策略验证并取消**：联网查 Artificial Analysis + Arena 排名，Kimi K2.6 对 v4-pro/GLM-5.1 无显著优势（Intelligence Index 54 vs 52/51，GDPval-AA 被 v4-pro 反超，Code Arena 被 GLM-5.1 碾压），历史优先规则已过时。Ultrabrain 统一到 glm-5.1。
- **小 Agent fallback 链扩展**：copilot 弱模型 + 大 Agent 全链，确保 fallback 最深。

### 模型排名验证（联网，2026-06-20）
| 基准 | Kimi K2.6 | DeepSeek V4 Pro | GLM-5.1 |
|---|---|---|---|
| AA Intelligence Index | 54 (#1 开源) | 52 (#2) | 51 (#3) |
| GDPval-AA (agentic) | 1484 | 1554 (#1 开源) | 1535 |
| Arena Code Arena | #7 (1522) | #17 (1459) | #6 (1531) |
| Arena Text Arena | #11 | #14 | #9 |
| 上下文 | 262K | 1M | 200K |

### OMO Agent Fallback 最终状态
| Agent 类型 | 主模型 | Fallback 链 | 链长 |
|---|---|---|---|
| **Sisyphus**（编排总管，TUI 默认） | nvidia-deepseek-v4-pro | 1M-only：NIM→MS→Plan→便宜→中等→贵→grok | 9 |
| **大 Agent ×7**（oracle/deep/ultrabrain/visual/high/artistry/writing） | nvidia-glm-5.1 | CF→OR→NIM kimi→CF glm→Zen→NIM 1M→Zen mimo→NIM v4→MS→NIM m3→Plan→便宜→中等→grok | 17 |
| **小 Agent ×3**（junior/quick/unspecified-low） | copilot-claude-haiku-4-5 | copilot + 大链 | 18 |
| **Review ×7**（GLM/Deepseek/Kimi/Qwen/Minimax/Mimo/Grok） | 各家独立 | 短链（评审 prompt 短） | 0-2 |

### 定价档次（新增全局规则）
| 档次 | 定价级别 | 示例 |
|---|---|---|
| 4 | 便宜按量付费 | DeepSeek 官方、MiMo 官方 |
| 5 | 中等按量付费 | 国产比 DS/MiMo 贵比四巨头便宜（火山按量、阿里云按量等） |
| 6 | 贵按量付费 | Grok、Gemini、Claude、GPT 官方 |

### 模型上下文（联网核实）
| 模型 | 上下文 | 备注 |
|---|---|---|
| DeepSeek V4 Pro/Flash | 1M | 官方/HF/NIM |
| GLM-5.2 (vc/七牛) | 1M | Z.AI 官方；CF 临时 262K |
| GLM-5.1 | 200K | Z.AI 官方/NIM |
| Kimi K2.6/K2.7-code | 256K | Kimi 官方 |
| Nemotron 3 Ultra | 1M（最大） | NIM 文档 |
| MiniMax M3 | 1M | MiniMax 官方/NIM/ModelScope |
| Qwen 3.7 Max | 1M | 阿里云官方 |

### 全端同步 ✅
C: | D: | racknerd | jstq | dmit | GitHub | E:\Codes×12 全部同步
C: | D: | racknerd | jstq | dmit | GitHub | E:\Codes×12

## 项目特有规则（保留）

## ⚠️ 【最高优先级】修改代码必须评审（不可跳过）

- **任何代码修改前必须调用多模型评审，无例外**
- **Git pre-commit hook 会硬阻断未评审的提交，没有后门**
- **禁止 `SKIP_REVIEW=1` 或 `ALLOW_UNREVIEWED_EDIT=1` 绕过评审**
- **强制排除规则**：主模型是哪家的，**严禁**调用同家 ReviewXXX 评审——同一个模型写代码再自己评审自己，纯浪费 Token 且无交叉验证意义
- 评审流程：改代码 → `task(category="ReviewXXX")` 调用不同模型评审 → M≥2 通过 → `mark-review-passed` → commit
- **无论用户是否在当条消息中强调"禁止跳过评审"，都必须走评审流程**
- 主模型是 MiMo 则用 ReviewGLM + ReviewKimi + ReviewDeepseek + ReviewQwen（排除 ReviewMimo）
- 主模型是 DeepSeek 则用 ReviewGLM + ReviewKimi + ReviewQwen + ReviewMimo（排除 ReviewDeepseek）

## Hermes-Agent 配置自动同步到 GitHub（关键）

- **每次修改 Hermes-Agent 配置**（三个 `config.yaml`、skills、scripts、systemd 服务文件等）**并验证正确后**，必须自动同步到 GitHub：
  ```bash
  git clone git@github.com:Fatty911/Personal_commonly_used.git /tmp/hermes-sync
  cd /tmp/hermes-sync
  # 复制以下文件：
  #   /root/.hermes/config.yaml → ai_tools/hermes-agent/config.yaml
  #   /root/.hermes/profiles/me138/config.yaml → ai_tools/hermes-agent/profiles/me138/config.yaml
  #   /root/.hermes/profiles/me152/config.yaml → ai_tools/hermes-agent/profiles/me152/config.yaml
  #   /root/.hermes/skills/ → ai_tools/hermes-agent/skills/
  #   /root/.hermes/scripts/ → ai_tools/hermes-agent/scripts/
  #   /root/.config/systemd/user/hermes-gateway-me*.service → ai_tools/hermes-agent/systemd/
  git add ai_tools/hermes-agent/ && git commit -m "hermes-agent: 同步 racknerd 生产配置" && git push
  ```
- **禁止推送含真实 API key 的 .env 文件**；须用 `sed 's/=.*/=REDACTED/'` 去敏后再生成 `.env.example`
- **同步时机**：每次改完配置 → 验证正确 → 立即执行上述流程 → 再发结论给用户
- **已有案例**：2026-06-19 改了 `model.provider`、`terminal.backend` 等多项配置，只在 VPS 上生效，未同步到 GitHub 备份；且初版执行时只提取了 .git 目录导致删除了 89 个仓库文件（已 revert 恢复）
