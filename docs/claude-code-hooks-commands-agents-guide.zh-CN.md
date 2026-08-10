# Claude Code Hooks、Commands/Skills 与 Agents 深入指南

> 本文以本仓库当前代码为案例，并以 2026-08-08 获取的 Claude Code 官方文档为语义依据。Claude Code 更新很快；仓库是一个“为生命周期事件播放声音”的示例，不应把其中的实验结论当成永久 API 契约。权威字段和事件列表请随版本核对[官方 Hooks reference](https://code.claude.com/docs/en/hooks)、[Skills 文档](https://code.claude.com/docs/en/skills)和[Subagents 文档](https://code.claude.com/docs/en/sub-agents)。

## 1. 先建立正确的心智模型

这三个系统并不是同一层的三种 agent：

| 系统 | 本质 | 何时发生 | 是否拥有独立上下文 |
|---|---|---|---|
| Commands（现在统一到 Skills） | 可复用的提示词/工作流入口 | 用户输入 `/name`，或允许模型自动加载 skill 时 | 默认没有；`context: fork` 时进入子 agent |
| Agents / subagents | 独立的模型执行者 | 主 agent 调用 `Agent` 工具、用户点名，或 skill 指定 fork | 有独立 context window、system prompt、工具与权限 |
| Hooks | Claude Code 生命周期事件上的拦截器/观察器 | prompt、工具、agent、压缩、会话等事件前后 | `command/http/mcp_tool` 本身不是 agent；`prompt/agent` hook 会调用模型 |

因此，**command 可以编排 agent，agent 可以带自己的 hooks，hook 又可以是 agent 型或 MCP-tool 型**。这叫组合，不是名称继承，也不是对象嵌套覆盖。

## 2. 本仓库的结构

```text
.
├── CLAUDE.md                         # 项目级长期说明和维护约束
├── README.md                         # 安装入口、版本/变更概览
├── .mcp.json                         # elicit MCP server
├── .claude/
│   ├── settings.json                 # 项目级 30 个生命周期 hook 注册
│   ├── commands/
│   │   ├── commit.md                 # /commit
│   │   └── workflows/
│   │       ├── workflow-add-hook.md  # /workflows:workflow-add-hook
│   │       └── workflow-changelog.md # /workflows:workflow-changelog
│   ├── agents/
│   │   ├── claude-code-hook-agent.md
│   │   ├── claude-code-test-agent.md
│   │   └── workflows/
│   │       └── workflow-changelog-agent.md
│   └── hooks/
│       ├── HOOKS-README.md           # 本项目 hook 说明
│       ├── config/hooks-config.json  # 脚本自己的开关（不是 CC hook schema）
│       ├── scripts/hooks.py          # 所有事件共用的 stdin→选音→记录→播放程序
│       └── sounds/...                # 主会话和 agent 专用音频
├── install/                          # 三个平台可复制的 settings 文件
├── demo/                             # 生命周期可视化 demo
├── presentation/                     # 演示页面
├── changelog/                        # 漂移检查记录/清单
└── tests-agents-hook/                # agent hook 人工测试产物
```

主链路非常简单：`.claude/settings.json` 把多个事件都指向同一个 `hooks.py`；Claude Code 在事件发生时把 JSON 写入脚本 stdin；脚本读取 `hook_event_name`，检查自己的配置开关，记录 JSON，按事件选声音并异步启动平台播放器。这个脚本不向 stdout 返回控制 JSON，所以它的功能是**观察和副作用**，不会修改工具输入、阻止工具或给下一次模型调用注入上下文。

仓库的 `hooks-config.json` 只是 `hooks.py` 自行读取的业务配置。Claude Code 不认识 `disablePreToolUseHook` 这类键；真正让 Claude Code 完全关闭 hooks 的是 settings 中的 `disableAllHooks`。

## 3. Commands / Skills 系统

### 3.1 名称如何产生

官方现在把 custom commands 合并进 Skills：旧的 `.claude/commands/x.md` 仍兼容，新项目优先写 `.claude/skills/x/SKILL.md`。

本仓库仍用旧目录，因此：

* `.claude/commands/commit.md` → `/commit`
* `.claude/commands/workflows/workflow-add-hook.md` → `/workflows:workflow-add-hook`
* `.claude/commands/workflows/workflow-changelog.md` → `/workflows:workflow-changelog`

旧 command 的子目录形成 `目录:文件名` 命名空间。新 skill 通常由 skill 目录名决定可输入的命令名；frontmatter 的 `name` 是显示/元数据字段。若同名 skill 和 legacy command 同时存在，**skill 优先**。官方当前还规定 enterprise、personal、project 间存在 scope 优先级，plugin skill 则有 `plugin:skill` 命名空间；不要依靠同层重复名称。

### 3.2 Command 文件是什么

它不是 Python 函数，也不会在被读取时自动执行。Markdown 正文会展开为交给当前 Claude 的工作指令，可使用 `$ARGUMENTS` 等参数替换，也可在正文里要求 Claude 调工具。

本仓库的 `/workflows:workflow-changelog` 是一个**协调器 prompt**：它要求当前主 agent 并行调用两次 `Agent` 工具，然后等待、合并报告并执行验证清单。所谓“command 里面定义两个子 agent”并不准确：它只写了两个 `subagent_type` 引用。

#### 能否在 slash command 正文里临时“定义一个外部从未出现过的 agent”？

**不能仅靠写一个新的 `subagent_type` 名称来定义。** 例如在 command 中写“调用 `subagent_type: security-genius`”，但该名称既不是内置 agent，也没有通过 managed settings、`--agents`、`.claude/agents/`、`~/.claude/agents/` 或 plugin 注册，Claude Code 的 agent registry 就无法解析它，调用会失败；command 正文不是 agent definition registry。

有三种容易混淆、但合法的做法：

1. **临时任务提示词，不是临时 agent 类型**：调用已经存在的 `general-purpose` agent，把全新的角色、目标和输出格式放进这一次 `Agent` tool 的 prompt。它可以表现得像临时专家，但其模型、工具和权限仍来自 `general-purpose`，也不能在其他调用中用这个临时角色名寻址。
2. **先创建，再调用**：command 可以要求主 Claude 先写入 `.claude/agents/security-genius.md`，待 Claude Code 发现并注册后再调用 `security-genius`。这会修改项目配置，不是 command 内联定义；新建首个 `agents` 目录等情况可能需要重启，而且执行 workflow 时动态改配置不如预先提交稳定。
3. **启动会话时注入**：使用 `claude --agents '{...}'` 传入会话级定义；在 Claude Agent SDK 中则通过 SDK 的 `agents` option 程序化定义。此时 agent 确实不需要存在于仓库文件中，但仍然是在 command 运行前/SDK options 中注册，而不是由 command 正文声明。

本项目的 `claude-code-guide` 正是第一句话中“外部没看到、但 registry 已经存在”的另一种情形：它是 Claude Code 内置 agent，所以 command 可以直接引用。它并不是该 command 临时创造出来的。

### 3.3 Skill 与 Agent 的真正嵌套

推荐的新写法可以显式让 skill 在子 agent 中运行：

```yaml
---
name: review
description: 审查当前改动
context: fork
agent: code-reviewer
disable-model-invocation: true
---

审查 $ARGUMENTS，输出按严重程度排序的问题。
```

`context: fork` 建立独立上下文，`agent` 选择 agent 类型；若省略，使用默认通用 agent。反过来，subagent frontmatter 的 `skills:` 是“启动时预加载技能内容”，不是在 agent 内注册另一个 agent。

### 3.4 模型在哪里选择

模型有三层，不能混为一谈：

1. **主会话模型**：通常由启动参数、settings 或交互式 `/model` 决定。`workflow-changelog.md` 没有 `model` 字段，所以 slash command 协调部分继续使用当时的主会话模型。
2. **自定义 agent 模型**：由 agent frontmatter 的 `model` 决定；可使用 `sonnet`、`opus`、`haiku`、完整 model ID 或 `inherit`。本仓库三个自定义 agent 都显式写了 `model: opus`，所以 `workflow-changelog-agent` 用 Opus；内置 `claude-code-guide` 的模型由 Claude Code 内置定义决定，而不是这个 command 决定。
3. **Skill 本次 turn 的模型**：新版 Skill frontmatter 也支持可选的 `model`。普通 skill 中它覆盖当前 turn，下一条用户 prompt 恢复 session model；与 `context: fork` 一起使用时，它设置 forked subagent 的模型。旧 command 虽兼容很多 skill frontmatter，但本仓库的 workflow 文件没有声明该字段。

所以“没看到模型选择项”并不是漏掉一个必填配置：`model` 本来就是可选的。缺省时沿用当前会话或所选 agent definition 的规则。若希望 workflow 的研究 agent 使用 Sonnet，应改 `.claude/agents/workflows/workflow-changelog-agent.md` 中的 `model`；若希望协调器整轮换模型，则迁移为 Skill 并在 frontmatter 设置 `model`，或在执行前用 `/model` 选择。

## 4. Agents 系统与本项目的三个自定义 agent

### 4.1 Agent 名称以什么为准

Agent 文件由“YAML frontmatter + Markdown system prompt”构成。身份以 frontmatter 的 `name` 为准，**不是文件名，也不是子目录名**；`description` 告诉主模型何时委派，正文是子 agent 的 system prompt。常用字段包括 `tools`/`disallowedTools`、`model`、`permissionMode`、`mcpServers`、`hooks`、`skills`、`maxTurns`、`memory`、`background`、`isolation` 和 `color`。

当前官方 scope 优先级是：managed > `--agents` > project `.claude/agents/` > user `~/.claude/agents/` > plugin。项目内从 cwd 向 repo root 扫描时，同名定义由离 cwd 最近者胜出；**同一个目录树/同一层的重复 `name` 没有可靠优先级，可能由文件系统读取顺序决定，应视为配置错误**。

### 4.2 本仓库有哪些 agent

1. `claude-code-hook-agent`：执行读文件、联网、写文件、Bash、故意失败等操作，用来听 agent 生命周期声音；frontmatter 内配置 agent-scoped hooks。
2. `claude-code-test-agent`：相似的人工探测 agent，但把触发事件写入 `tests-agents-hook/agent-hook-fired.log`，用于判断哪些 hook 实际触发。
3. `workflow-changelog-agent`：读取官方文档、changelog 与本地文件，输出 hook 漂移分析；由 changelog workflow 引用。

此外 `/workflows:workflow-changelog` 引用了 `claude-code-guide`。它没有出现在本仓库 `.claude/agents/`，因为它是 Claude Code 内置 helper agent。

### 4.3 “command 和 agents 里重复的名称，以哪个为准？”

本仓库看起来重复的是 `workflow-changelog-agent`：

* `.claude/agents/workflows/workflow-changelog-agent.md` 的 `name` **定义** agent；
* `.claude/commands/workflows/workflow-changelog.md` 中的 `subagent_type: "workflow-changelog-agent"` **引用**该 agent。

两者不是竞争定义，所以不存在“以哪个为准”。调用时先用字符串查 agent registry，找到的定义决定模型、工具和 system prompt；command 中随 `Agent` 调用传入的 task prompt 是本次任务说明，会与 agent 自己的 system prompt共同作用，但不会改名。

如果你真的又建一个同名 agent，按上一节的 scope 规则解析。一个同名 command/skill 与 agent 也不冲突，因为 `/foo` command namespace 与 `Agent(subagent_type="foo")` agent namespace彼此独立。

## 5. Hooks 要怎么写

### 5.1 最小可用 command hook

必须有：

1. 一个受支持的事件名，例如 `PreToolUse`；
2. 事件下的 hook group；
3. group 中的 `hooks` 数组；
4. handler 的 `type`；若是 `command`，还必须有 `command`（新格式也支持 `command` + `args` 的 exec form）；
5. 可执行程序读取 stdin JSON，并用退出码/stdout/stderr表达结果。

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/check.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

`matcher` 通常可省略，省略即匹配全部；它匹配什么取决于事件（工具事件匹配 tool name，`SubagentStart` 匹配 agent type 等）。`timeout`、`statusMessage`、`once`、`async` 等都是按需要选用，并非最小必需项。不要把本仓库统一使用 `async: true` 当成通用最佳实践：**需要阻止、改写、注入上下文的 hook 必须同步等待结果**；async hook 的结果不能影响已经继续推进的当前生命周期。

### 5.2 五种 handler

当前官方 reference 列出：

* `command`：本地进程，stdin 收 JSON，退出码和 stdout JSON 回传；最确定、最适合策略执行。
* `http`：把同一 JSON POST 给 URL，由 HTTP 状态/response body 回传。
* `mcp_tool`：Claude Code 直接调用已连接 MCP server 的指定 tool，可用 `${tool_input.file_path}` 一类模板映射 input。
* `prompt`：一次 LLM 判定，默认快速模型，返回 `{ "ok": true }` 或 `{ "ok": false, "reason": "..." }`。
* `agent`：实验性，多轮 verifier，可用 Read/Grep/Glob 等工具调查后给出同样的 ok/reason，最多约 50 turns；生产关键策略仍优先 deterministic command hook。

不是每个事件都支持五种类型。尤其 `SessionStart`/`Setup` 的支持集更窄；配置前应查对应版本 reference。

### 5.3 stdin 和输出协议

所有事件至少包含类似 `session_id`、`transcript_path`、`cwd`、`hook_event_name` 的公共字段；工具事件再有 `tool_name`、`tool_input`、`tool_use_id`，Post 事件还有 result/error。不要自行猜 schema，应按事件解析且忽略未知字段。

command hook 的基本输出规则：

* exit `0`：成功；若 stdout 是合法 JSON，Claude Code 解析控制字段。
* exit `2`：blocking error；stdout/JSON 被忽略，stderr 成为阻止原因；具体阻止对象因事件而异。
* 其他 exit code：多数事件视作非阻塞 hook error，原流程继续。

通用 JSON 字段和事件专用字段要分清。常见通用能力包括 `continue`、`stopReason`、`suppressOutput`、`systemMessage`；真正给模型的内容通常应使用事件的 `hookSpecificOutput.additionalContext`。`systemMessage` 多数情况下是展示给用户而非模型，不能当作可靠 handoff。

## 6. Hooks 如何接入并影响 Claude Code 生命周期

### 6.1 PreToolUse：在副作用发生前

```text
模型产生 tool_use
  → matcher 选中 PreToolUse handlers
  → hooks 执行并合并决策
  → deny / ask / defer / allow
  →（若允许）按 updatedInput 执行工具
```

command hook 可返回：

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "permissionDecisionReason": "validated",
    "updatedInput": {"command": "npm test"},
    "additionalContext": "这是生产环境，请谨慎。"
  }
}
```

主要影响方式：

1. `deny`：不执行工具，并把理由反馈给 Claude；Claude 可改方案。
2. `ask`：进入正常权限询问。
3. `defer`：保留 pending tool call，结束当前处理并允许以后恢复（这比一般所谓 handoff 更接近正式的延后交接）。
4. `allow`：跳过当前 hook 层的阻止，但仍受其他权限/安全规则约束。
5. `updatedInput`：执行修改后的完整 input；这是“修改将发生什么”的关键机制。
6. `additionalContext`：给模型补充上下文，但工具仍按决策执行。

多个 PreToolUse 决策的当前优先级是 `deny > defer > ask > allow`。因此并不是“最后一个 hook 覆盖前一个”。

### 6.2 PostToolUse / PostToolUseFailure：副作用之后

```text
工具已成功/失败
  → PostToolUse 或 PostToolUseFailure
  → 原始/更新后的 tool result + additionalContext
  → 下一次模型调用
```

可用方式：

* `additionalContext`：随 tool result/error 注入下一次 Claude 上下文，例如告诉模型修复建议。
* PostToolUse 的 `updatedToolOutput`：替换**模型看到的**工具输出（必须匹配内置 tool output schema）。
* `decision: "block"` + `reason`：告诉 Claude 结果有问题并影响后续 loop；但工具已经运行，无法撤销磁盘写入、命令或网络副作用。
* PostToolBatch：所有并行 tool 完成后只运行一次，适合基于整批结果注入统一上下文；`decision: block` 或 `continue: false` 可在下一次模型调用前停 loop。

这就是用户所问的 handoff：Claude Code 没有要求你调用一个统一名为 `handoff()` 的 hook API；**handoff 是事件输出协议完成的**。在 PostToolUse 中，`additionalContext`/`updatedToolOutput` 会进入下一轮模型输入；纯日志、stderr（exit 0）或多数 `systemMessage` 不会成为模型上下文。

### 6.3 Prompt、Stop 与 Subagent 生命周期

* `UserPromptSubmit` 可阻止 prompt，也可把 stdout/context 加入 Claude 处理用户请求前的上下文。
* `SubagentStart.additionalContext` 在子 agent 第一次 prompt 前注入。
* `SubagentStop decision:block` 会把 reason 作为下一条指令让**该子 agent**继续，而不是交给 parent。
* 若要在子 agent 返回后影响 parent，官方建议匹配 parent 的 `Agent` tool 的 `PostToolUse`，再注入 `additionalContext`。
* `Stop decision:block` 或 Stop 的 `additionalContext` 可让当前 Claude 继续工作。必须检查 `stop_hook_active`，避免无限停止循环；Claude Code 自身也有连续继续保护。

### 6.4 Hook 中调用 LLM、MCP 和工具

是的，但路径不同：

* `prompt` hook：让 LLM 对输入做单次语义判断，适合“任务是否完成”这类难以硬编码的问题。
* `agent` hook：LLM 可多轮读文件/搜索/检查，再返回 ok/reason，适合验证测试或跨文件事实。
* `mcp_tool` hook：直接调用 MCP 工具，工具的结构化结果再按该事件规则参与决策。
* `command` hook：你的 Python/Node 程序当然也能自行调用 Anthropic API、启动 SDK agent 或调用 MCP client，但此时你必须自己做超时、鉴权、错误处理和输出协议映射。

模型不是“代码覆盖不了就一定调用”的默认兜底。安全白名单、路径限制、secret 检测应优先确定性代码；模糊语义评审才使用 prompt/agent，并考虑模型误判、prompt injection、成本和延迟。MCP server 在 `SessionStart`/`Setup` 早期可能尚未连接，也要设计失败策略。

## 7. 本仓库 hooks 的逐步运行示例

以主会话调用 Bash 为例：

1. Claude 模型产生 Bash tool call。
2. Claude Code 在 `.claude/settings.json` 找到 `PreToolUse` group。
3. 因没有 matcher，该 group 匹配；它异步启动 `python3 .../hooks.py`。
4. Claude Code 把含 `hook_event_name=PreToolUse`、`tool_name=Bash` 和 `tool_input.command` 的 JSON 写入 stdin。
5. `hooks.py` 读取 `--agent` 参数与 stdin，检查事件开关，记录输入。
6. 若 Bash command 像 git commit，脚本选专用音效，否则按 `HOOK_SOUND_MAP` 选音效，并启动 `afplay`/`paplay`/`winsound`。
7. 脚本 exit 0 且没有控制 JSON；因为 handler 还是 `async: true`，Claude Code 不等它，Bash 按正常权限系统继续。
8. Bash 完成后，同样触发异步 `PostToolUse`，再响一次；若执行后失败则触发 `PostToolUseFailure`。

Agent 文件里的 hooks 是同一协议，但只在该 agent 活跃期间注册，并通过 `--agent=...` 让脚本改用 `AGENT_HOOK_SOUND_MAP`。它们不会覆盖项目 settings hooks；匹配的 hooks 会共同存在。因此可能听到主配置声音和 agent-scoped 声音，取决于版本、事件和配置。

## 8. 把模型调用无缝放进代码：你记得的 API

最可能是 **Claude Agent SDK 的 `query()`**（TypeScript/Python 都有）：它把 Claude Code 的 agent loop 作为库放进程序；你传 prompt/options，异步迭代消息，模型可在 loop 内调用允许的工具。需要多轮交互和中途控制时，用 `ClaudeSDKClient`。SDK 还提供：

* in-process MCP server / `@tool`（Python）或 `tool()`（TypeScript），把普通程序函数暴露成模型工具；
* `agents` 配置定义 subagents；
* hooks callbacks 拦截 tool 生命周期；
* `query()` 的 structured output 把最终结果约束成 JSON schema。

它与 Claude Code CLI hooks 要区分：前者是“你的应用拥有 agent loop”，后者是“Claude Code 拥有 loop，并在固定事件回调你的代码”。如果你只想在现有 CLI 的 Stop 点做一次判断，`type: prompt` 更小；如果你正在开发自己的 agent 产品，则用 Agent SDK `query()`/`ClaudeSDKClient`。

类似方案并非 Claude 独有：

| 方案 | 代码内模型/agent 调用 | 工具融合 | 多 agent 交接 |
|---|---|---|---|
| [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) | `Runner.run()` / `Runner.run_sync()` / `Runner.run_streamed()` | `function_tool`、MCP | handoffs、agents-as-tools、guardrails、tracing |
| [Google Agent Development Kit](https://google.github.io/adk-docs/) | `Runner` / sessions | function tools、OpenAPI、MCP | sub-agents、workflow agents、agent transfer |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) | 编译 graph 后 `invoke`/`stream` | tool nodes | graph edges、Command/goto、supervisor 模式 |
| [Microsoft AutoGen](https://microsoft.github.io/autogen/stable/) | `AssistantAgent.run()` / teams | function tools、workbench、MCP | teams、handoffs/swarm |

概念上它们都能把“模型 → 工具 → 结果 → 模型”变成可编程 loop，但抽象层不同。不要因为都叫 hook/handoff 就假设输出协议兼容；Claude Code hook JSON 只由 Claude Code 消费。

## 9. 推荐学习与实验顺序

1. 先读 `.claude/settings.json` 和 `hooks.py`，用 `claude --debug` 与 `/hooks` 观察真实 stdin/event。
2. 把一个 `PreToolUse` 改为同步实验 hook：先只记录 JSON，再试 `deny`，再试 `updatedInput`。
3. 写一个 PostToolUse `additionalContext` 实验，确认下一轮 Claude 能引用它；再比较 `systemMessage` 只影响 UI 的情况。
4. 手动运行 `/workflows:workflow-changelog`，观察主 context、两个 `Agent` tool call、各自独立 transcript 与 parent 汇总。
5. 新建同名 command 和 agent，验证 namespace 独立；不要制造两个同 scope、同 `name` 的 agent 来依赖未定义顺序。
6. 最后比较 deterministic command hook、`prompt` hook、`agent` hook 与 `mcp_tool` hook 的延迟、费用、稳定性和可解释性。

## 10. 本仓库值得注意的版本漂移

本项目文档和 `CLAUDE.md` 固定声称“30 hooks”，而 2026-08-08 的官方 reference 已出现额外事件（例如 `DirectoryAdded`），并明确写了五种 handler 与“agent/skill frontmatter 支持所有 hook events”。仓库自己的“仅 6 个事件在 agent session 触发”来自较早版本的实测，`HOOKS-README.md` 也已经提示需要重新测试。

学习这个仓库时应把内容分为两类：

* **稳定架构示例**：settings 注册 → stdin JSON → 脚本处理；command 编排 Agent；agent frontmatter scoped hooks。
* **版本快照**：事件总数、哪些 agent hook 会触发、字段名称、支持的 handler 类型。此类结论必须以你安装的 `claude --version`、`/hooks`、schema 和最新官方 reference 为准。

## 11. 官方延伸阅读

* [Hooks reference](https://code.claude.com/docs/en/hooks)
* [Hooks guide](https://code.claude.com/docs/en/hooks-guide)
* [Skills（含 legacy custom commands）](https://code.claude.com/docs/en/skills)
* [Custom subagents](https://code.claude.com/docs/en/sub-agents)
* [Claude Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
* [Agent loop](https://code.claude.com/docs/en/agent-sdk/agent-loop)
* [SDK custom tools / in-process MCP](https://code.claude.com/docs/en/agent-sdk/custom-tools)
* [SDK hooks](https://code.claude.com/docs/en/agent-sdk/hooks)

## 12. 最新官方协议下的代码要求与标准模板（2026-08-10 核对）

### 12.1 先纠正“必须包含哪些模块”

Anthropic **没有规定 hook 程序必须使用 Python，也没有规定必须 import 某些模块或继承某个基类**。`type: command` 的契约是进程协议：Claude Code 启动任意可执行命令，把本次事件的 JSON object 写到 stdin；程序用 exit code、stderr，以及可选的 stdout JSON object 回应。你可以使用 Python、Node、Go、Rust、Bash 或任何可执行程序。[官方 Configuration](https://code.claude.com/docs/en/hooks#configuration)定义的是 event → matcher group → handler 三层配置，[Hook input and output](https://code.claude.com/docs/en/hooks#hook-input-and-output)定义的是进程边界。

本仓库提供的 [Python 标准起步模板](../.claude/hooks/templates/standard-hook.py)只使用标准库：

* `json`：读取 stdin 和序列化唯一的 stdout JSON；
* `sys`：stdin/stdout/stderr 与 exit code；
* `typing`：只为类型标注，可删除。

这些是模板的工程选择，不是 Anthropic 强制模块。模板对应的可复制配置是 [`settings.example.json`](../.claude/hooks/templates/settings.example.json)。

### 12.2 配置文件的最小和推荐规则

hook 可以放在 project `.claude/settings.json`、local `.claude/settings.local.json`、user `~/.claude/settings.json`、managed settings、plugin `hooks/hooks.json`，或 skill/agent frontmatter。不同 settings scope 的 hook 会合并而不是相互覆盖。项目 hook 会执行本机代码，因此首次使用仍受 workspace trust 与组织策略影响。完整位置表见[官方 Hook locations](https://code.claude.com/docs/en/hooks#hook-locations)。

handler 的唯一公共必填字段是 `type`。不同类型再有各自必填项：

| 类型 | 必填 | 谁执行、怎样返回 |
|---|---|---|
| `command` | `type`, `command` | 本地进程；stdin JSON，exit code/stderr/stdout JSON |
| `http` | `type`, `url` | HTTP POST；2xx body 使用同一 JSON output schema |
| `mcp_tool` | `type`, `server`, `tool` | 已连接 MCP tool；text content 按 command stdout 解释 |
| `prompt` | `type`, `prompt` | Claude 单轮判断；Claude Code 自动消费 `{ok, reason}` |
| `agent` | `type`, `prompt` | 实验性多轮 verifier，能用 Read/Grep/Glob 等工具 |

公共可选字段是 `if`、`timeout`、`statusMessage`、`once`；`command` 另有 `args`、`async`、`asyncRewake`、`shell`。当前官方默认 timeout 通常为 command/http/MCP 600 秒、prompt 30 秒、agent 60 秒，但个别事件有更小预算。具体字段以[Hook handler fields](https://code.claude.com/docs/en/hooks#hook-handler-fields)为准。

推荐使用 **exec form**，即 `command: "python3"` 加 `args: [...]`，避免 shell 再次解析路径和特殊字符。只有需要 pipe、redirect 或 `&&` 时才用 shell form。`matcher` 可省略表示全匹配；它匹配哪个输入字段取决于 event。所有匹配到的 handlers 会并行运行，不保证书写顺序。

### 12.3 Command hook 的 stdout、stderr 与 exit code

必须牢记以下边界：

* exit `0` + 无 stdout：成功，不施加控制。
* exit `0` + stdout JSON：结构化控制。**stdout 必须只包含一个 JSON object**；普通 log 不要混进去。
* exit `2`：blocking error；Claude Code 忽略 stdout JSON，使用 stderr 作为理由。阻止效果依事件而异。
* 其他 exit code：对大多数事件是 non-blocking hook error，原动作继续。
* stderr 在 exit `0` 时通常只进 debug log，不会自动进入模型上下文。

也就是说，Python 的 `print("debug")` 如果写到 stdout，会破坏 JSON。日志应写 stderr 或文件；真正返回协议 JSON 时用一次 `json.dump(..., sys.stdout)`。官方明确要求“exit-code signaling”和“exit 0 + structured JSON”二选一，见[Exit code output](https://code.claude.com/docs/en/hooks#exit-code-output)与[JSON output](https://code.claude.com/docs/en/hooks#json-output)。

### 12.4 哪些文字给用户，哪些文字给主模型

| 输出 | 接收者/效果 |
|---|---|
| `systemMessage` | 显示给用户；不是给 Claude 的 handoff |
| `stopReason` | `continue:false` 时显示给用户；不显示给 Claude |
| `hookSpecificOutput.additionalContext` | 作为 system reminder 注入 Claude context，在下一次 model request 可见 |
| top-level `reason` | 支持 block 的事件中作为反馈；例如 Stop/SubagentStop 可成为继续工作的指令 |
| exit `2` 的 stderr | 依 event 反馈给 Claude 或用户；不能假设所有事件一致 |
| 普通 stdout | 只有少数事件把它当 context；生产代码应显式返回 JSON，避免依赖特例 |
| `updatedToolOutput` | PostToolUse 中替换 Claude 看到的结果，不撤销已经发生的副作用 |
| `displayContent` | MessageDisplay 只改屏幕显示，不改 transcript，也不改 Claude 所见内容 |

`additionalContext` 是最标准的“返回给主模型的文本”：

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "The edited file is generated from src/schema.ts."
  }
}
```

官方建议把它写成环境事实，而不是伪装成高优先级 system command，否则可能触发 prompt-injection 防护。输出字符串上限为 10,000 characters，超限会落盘并用 preview/path 替代。详见[Add context for Claude](https://code.claude.com/docs/en/hooks#add-context-for-claude)。

### 12.5 哪些 hook 能直接调用大模型

最新版内建两条模型路径，不需要你的 Python 自己调用 Anthropic API：

**单轮 `prompt` hook：**

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "prompt",
            "prompt": "Check whether every requested deliverable is complete. $ARGUMENTS",
            "model": "haiku",
            "timeout": 30,
            "continueOnBlock": true
          }
        ]
      }
    ]
  }
}
```

Claude Code 把 hook input 和 prompt 交给模型，并自动要求 `{ "ok": true }` 或 `{ "ok": false, "reason": "..." }`。`model` 可选，默认 fast model。不同 event 对 `ok:false` 的处理不同，尤其 PermissionRequest/PermissionDenied 不能靠这个布尔结果完成细粒度 deny/retry；应查[Prompt-based hooks](https://code.claude.com/docs/en/hooks#prompt-based-hooks)。

**多轮、可用工具的实验性 `agent` hook：**

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "agent",
            "prompt": "Inspect the repository and verify required tests passed. $ARGUMENTS",
            "model": "sonnet",
            "timeout": 120
          }
        ]
      }
    ]
  }
}
```

它会启动最多约 50 turns 的 verifier，可读文件和搜索代码，最终同样返回 ok/reason。官方仍标记为 experimental，生产安全策略优先 deterministic command hook，详见[Agent-based hooks](https://code.claude.com/docs/en/hooks#agent-based-hooks)。

支持全部五种 handler 的事件目前包括 PreToolUse、PermissionRequest、PostToolUse、PostToolUseFailure、PostToolBatch、UserPromptSubmit、UserPromptExpansion、Stop、SubagentStop、TaskCreated、TaskCompleted、TeammateIdle、PermissionDenied。其余事件的类型支持集更窄；`SessionStart`/`Setup` 仅支持 command 和 MCP-tool。不要把 prompt/agent handler 复制到任意事件。

`mcp_tool` 是另一条无需自写 MCP client 的路径，但 server 必须已经连接；SessionStart/Setup 常早于连接完成。command 程序当然也能自行调用 Anthropic API 或 SDK，但那不属于 hook 协议要求，你要自行承担 API key、timeout、重试、费用、模型输出验证和 prompt injection 风险。

### 12.6 可运行标准模板怎样工作

[`standard-hook.py`](../.claude/hooks/templates/standard-hook.py)展示了推荐骨架：

1. 用 `json.load(sys.stdin)` 读取并验证 object；
2. 用 `hook_event_name` 做显式 dispatch；
3. PreToolUse 对 Bash 做确定性检查，deny 时返回带正确 `hookEventName` 的 `permissionDecision`；
4. PostToolUse 用 `additionalContext` 把事实交给下一次模型调用；
5. Stop 检查 `stop_hook_active`，避免 continuation 无限递归；
6. 只在有结构化结果时写一次 stdout JSON；诊断写 stderr；
7. 未处理事件或允许动作时 exit 0 且不输出。

复制 `settings.example.json` 的三个 groups 到项目 `.claude/settings.json` 即可试用。先用 `claude --debug` 检查输入/解析错误，再用 `/hooks` 确认实际加载来源。模板中的 destructive-command 字符串匹配只是教学示例，不是完整 shell parser；高风险生产策略还应结合 permissions deny rules、sandbox、严格解析和测试。Anthropic 也提供了一个更专门的[官方 Bash command validator reference implementation](https://github.com/anthropics/claude-code/blob/main/examples/hooks/bash_command_validator_example.py)。

### 12.7 同步、异步和安全规则

需要 allow/deny、改写 input/output 或立即注入 context 时，保持同步。`async:true` 只适用于 command hook，而且当前动作不会等待它，因此 `decision`、`permissionDecision`、`continue` 都不能控制已推进的动作；异步完成后的 `additionalContext` 要到下一次 conversation turn 才交给 Claude。`asyncRewake:true` 可在 exit 2 时唤醒 Claude。详见[Run hooks in the background](https://code.claude.com/docs/en/hooks#run-hooks-in-the-background)。

最后，command hook 拥有当前用户的文件系统权限。必须验证不可信 stdin、阻止 path traversal、避开 `.env`/keys/`.git` 等敏感路径、引用 shell 变量时加引号，优先使用绝对路径与 exec form。不要把 hook 当成安全沙箱；官方安全清单见[Security considerations](https://code.claude.com/docs/en/hooks#security-considerations)。
