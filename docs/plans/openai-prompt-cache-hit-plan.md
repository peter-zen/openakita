# OpenAI Prompt Cache Hit 改造方案

更新日期：2026-04-05

本文档只讨论一件事：

- 当 OpenAkita 调用 OpenAI 兼容大模型服务时，如何提高请求的 Prompt Cache Hit 比例，从而降低输入成本。

不讨论：

- OpenAkita 的业务功能
- 组织编排 / 项目 / 任务逻辑
- 前端 UI 展示逻辑

---

## 1. 目标

目标是让 OpenAkita 发给上游模型服务的请求，尽可能满足 Prompt Caching 的命中条件。

我们希望达到的结果：

1. 相同会话内连续多轮请求能稳定复用前缀缓存。
2. 同类请求在不同会话间也有更高概率命中缓存。
3. 在不明显破坏产品行为的前提下，优先做“低改动、高收益”的结构优化。

---

## 2. 官方规则摘要

基于 OpenAI 官方文档，Prompt Caching 的关键点是：

1. Prompt caching 是自动生效的，但要求请求存在足够长的完全相同前缀。
2. 缓存从前缀超过 1024 tokens 开始，之后按 128-token 递增命中。
3. 工具定义、图片、长系统提示等都可以进入缓存前缀，但前提仍然是前缀内容本身保持稳定。
4. `prompt_cache_key` 不是“强制命中开关”，它的作用更接近路由提示，用于提高相似请求命中同一缓存机器的概率。
5. Responses API 的 conversation state / `previous_response_id` 可以减少重复发送完整上下文，并通常带来更好的缓存利用与更低延迟。

官方参考：

- https://platform.openai.com/docs/guides/prompt-caching
- https://platform.openai.com/docs/guides/latency-optimization
- https://developers.openai.com/api/docs/guides/conversation-state

---

## 3. 当前代码现状

当前 OpenAkita 的 Responses API 路径主要特征如下。

### 3.1 请求层

文件：

- `src/openakita/llm/providers/openai_responses.py`

现状：

1. 每次请求都重新构建完整 `input`。
2. 当前显式设置了 `store = False`，见 `openai_responses.py:210-224`。
3. 当前没有传 `prompt_cache_key`。
4. 当前没有传 `prompt_cache_retention`。
5. 当前没有使用 `previous_response_id`。

这意味着：

- OpenAkita 当前是“每轮完整重放上下文”的无状态模式。
- 如果 prompt 前缀不稳定，缓存命中会非常差。

### 3.2 Prompt 组装层

文件：

- `src/openakita/prompt/builder.py`
- `src/openakita/core/agent.py`

现状：

1. Runtime 段在较前位置注入，见 `prompt/builder.py:368-388`。
2. Runtime 段包含当前时间、CWD、PATH 工具状态等动态内容，见 `prompt/builder.py:772-796`。
3. Session metadata 段包含 `session_id`、`message_count`、`sub_agent_count` 等会每轮变化的内容，见 `prompt/builder.py:799-850`。
4. `session_context` 是每轮在 `core/agent.py:1812-1823` 现算出来再注入 prompt 的。
5. 这些动态段出现在工具 catalog、技能 catalog、AGENTS.md 等大块静态内容之前。

这意味着：

- 请求最前面的 1k tokens 左右就已经变化。
- 即使后面的大段工具说明、技能说明、AGENTS.md 内容完全一致，也很难形成可复用的缓存前缀。

### 3.3 Usage 统计层

文件：

- `src/openakita/llm/providers/openai_responses.py`

现状：

当前只解析了：

- `input_tokens`
- `output_tokens`

见 `openai_responses.py:287-300`。

这意味着：

- 即使上游已经返回了 cached token 细分信息，OpenAkita 当前也未必会把它单独记录到本地统计里。
- 因此，应用内统计不一定能直接反映缓存命中；上游控制台数据更可信。

---

## 4. 根因判断

当前缓存命中低的主因不是：

- `Responses API` 本身
- `同步` 调用方式
- `流式` 调用方式

主因是：

1. **完整上下文每轮重发**
2. **动态内容出现在 prompt 前缀过早位置**
3. **缺少稳定的 `prompt_cache_key`**
4. **没有利用 Responses conversation state**

其中第 2 点是当前最关键的问题。

如果每轮请求在 prompt 的最前面就出现：

- 当前时间
- message_count
- session_id
- 实时工具状态

那么从缓存系统视角看，请求前缀几乎每轮都不同。

---

## 5. 改造原则

改造时遵循以下原则：

1. 先改“前缀稳定性”，再改“状态管理模式”。
2. 先做低风险结构优化，不立即切换到完全 stateful。
3. 所有会变化的信息都尽量后置，或改为按需工具查询。
4. 所有大块静态文本都尽量前置，作为稳定缓存前缀。
5. 如果上游是 OpenAI 兼容服务而非官方 OpenAI，本方案仍适用，但 `prompt_cache_key` / retention 是否被透传，需要上游服务支持。

---

## 6. 分阶段改造方案

## Phase 0：观测先行

目标：先把“到底有没有命中缓存”观察清楚。

改动：

1. 在 Responses provider 中补充对 cached token 细分字段的解析和记录。
2. 在本地 token usage 统计中增加：
   - `cache_read_input_tokens`
   - `cache_creation_input_tokens`
3. 在 debug / tracing 中记录本轮请求的：
   - prompt prefix hash
   - tool schema hash
   - skill catalog hash
   - `prompt_cache_key`

收益：

- 先看清楚“是完全不命中”，还是“偶尔命中但当前统计看不见”。

风险：

- 很低。

建议优先级：

- P0，最先做。

---

## Phase 1：最小改造，高收益

目标：不改变产品交互模式，只提高前缀稳定性。

### 1. Runtime / Session Metadata 后置

改动：

1. 将以下内容从 prompt 前部移到后部：
   - 当前时间
   - CWD
   - PATH 工具列表
   - 浏览器 / MCP / 工具实时状态
   - session_id
   - message_count
   - sub_agent_count
2. 对真正不需要写进 prompt 的内容，直接删除，改为通过工具查询。

建议：

- `当前时间` 不应进入缓存前缀。
- `message_count`、`session_id` 这类会话元信息不应阻断大段静态 prefix 的复用。

### 2. 静态大块前置

改动：

将以下内容尽量前置并保持稳定顺序：

1. core rules
2. identity
3. mode rules
4. AGENTS.md
5. tool catalog
6. skill catalog
7. MCP catalog

要求：

- 顺序固定
- 文本尽量 deterministic
- 不插入时间、计数、当前状态之类的动态字段

### 3. 增加稳定 `prompt_cache_key`

改动：

在 Responses request body 中传：

- `prompt_cache_key`

key 设计要求：

1. 不要包含 `session_id`
2. 不要包含时间戳
3. 不要包含 message_count
4. 只包含稳定分桶信息

推荐 key 结构：

```text
oak:{surface}:{mode}:{profile_or_agent}:{model_family}:{toolset_version}
```

示例：

```text
oak:desktop:agent:default:gpt5:toolset-v1
oak:org:agent:project-orchestrator:gpt5:toolset-v1
oak:cli:agent:default:gpt5:toolset-v1
```

注意：

- `prompt_cache_key` 不是命中保证，只是提高概率。
- 真正决定命中的仍然是“前缀必须稳定”。

收益：

- 这是最小改造里收益最高的一步。

风险：

- 低。

建议优先级：

- P1，优先做。

---

## Phase 2：进一步减少完整上下文重放

目标：减少每轮都发送完整历史。

### 方案 A：继续无状态，但压缩动态前缀

做法：

1. 继续保持 `store = False`
2. 压缩动态 session/history 注入
3. 尽量只让“最新用户消息”在前缀后部变化

优点：

- 风险低
- 不引入 OpenAI 侧状态依赖

缺点：

- 相比 stateful，缓存收益有上限

### 方案 B：切换到 Responses conversation state

做法：

1. 将 `store` 改为 `True`
2. 在同一会话链路中使用 `previous_response_id`
3. 不再每轮重发完整历史，只发送当前增量

优点：

- 通常能明显提高 cache utilization
- 能降低请求体体积和延迟

缺点：

- 要处理 OpenAI 侧状态依赖
- 要处理 response chain 生命周期
- 要明确数据保留与隐私策略

建议：

- 这一步作为可选深改，放在 Phase 1 完成之后再评估

建议优先级：

- P2。

---

## Phase 3：进一步做 deterministic prompt

目标：让工具/技能/catalog 文本在更多场景下保持完全一致。

改动建议：

1. 固定 tools 顺序
2. 固定 skills 顺序
3. 固定 schema 字段顺序
4. 去掉 catalog 内的动态统计项
5. 避免不同模式下生成“长得差不多但不完全一致”的 catalog 文本

收益：

- 对跨会话缓存命中率有帮助。

风险：

- 中等，容易牵扯提示词行为。

建议优先级：

- P3。

---

## 7. 推荐实施顺序

建议按这个顺序执行：

1. Phase 0：补观测
2. Phase 1：
   - Runtime / session metadata 后置
   - 静态 catalog 前置
   - 增加 `prompt_cache_key`
3. 观察一段时间：
   - 上游控制台 cached input tokens 是否明显增加
   - 首轮命中和多轮命中分别如何
4. 如果命中仍然不理想，再评估 Phase 2（conversation state）

不建议一上来就做：

- 全量切 `store=true`
- 直接引入 `previous_response_id` 链路

因为这会把“缓存优化”问题和“会话状态管理”问题绑在一起，排查成本更高。

---

## 8. 验证指标

实施后需要观察以下指标。

### 上游控制台

1. 是否出现 cached input tokens / cached input cost
2. 多轮会话第二轮起是否明显高于当前基线
3. 同类会话在不同用户之间是否也能出现部分命中

### OpenAkita 本地

1. `cache_read_input_tokens`
2. `cache_creation_input_tokens`
3. 每轮 request body 大小
4. TTFT / 总耗时
5. 首轮与后续轮次输入成本对比

### 回归检查

1. prompt 内容是否仍正确
2. 工具可见性是否未受影响
3. 多 Agent / Org / Skills 是否未因 prompt 重排而回归

---

## 9. 当前明确结论

基于当前代码，可以明确判断：

1. OpenAkita 当前低命中率的主因是 **prompt 前缀不稳定**。
2. `同步` 与 `流式` 不是决定性因素。
3. `Responses API` 不是问题本身。
4. 当前最值得先做的不是“换端点”，而是：
   - 后置动态段
   - 前置静态大块
   - 增加稳定 `prompt_cache_key`

---

## 10. 建议的下一步

下一轮改造建议只做 Phase 0 + Phase 1，不碰 Phase 2。

也就是：

1. 先补缓存命中观测
2. 重排 prompt 结构，稳定前缀
3. 增加 `prompt_cache_key`

这样可以用最小风险验证：

- 命中率是否显著改善
- 成本是否明显下降

如果这三步做完后命中率仍然低，再考虑把会话链路切到 `store=true + previous_response_id`。

