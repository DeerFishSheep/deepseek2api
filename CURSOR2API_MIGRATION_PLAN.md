# DeepSeek2API Tool Calling Migration Plan

## 目标

把 `cursor2api` 中更稳定的工具调用机制迁移到 `deepseek2api`，让 `deepseek2api` 在部署后：

- 更稳定地诱导模型触发工具调用
- 更可靠地解析工具调用结果
- 更少出现格式漂移、半截 JSON、空工具调用、重复调用
- 在 OpenAI 兼容接口和 Anthropic 兼容接口上保持一致行为
- 在不破坏现有 DeepSeek 账号轮换、PoW、会话管理逻辑的前提下升级工具链路

## 先说结论

“完美迁移”不能理解成把 `cursor2api` 的提示词和代码整段照抄到 `deepseek2api`。

原因很直接：

- `cursor2api` 的大量提示词是为了对抗 Cursor/Claude/Documentation Assistant 场景限制而写的
- `deepseek2api` 的上游不是 Cursor，而是 `chat.deepseek.com`
- `cursor2api` 的很多行为建立在 `Cursor API -> SSE -> 自定义响应事件` 这条链路上
- `deepseek2api` 当前是 `DeepSeek Web Chat -> prompt -> 文本/思维流 -> 兼容层响应`

所以真正应该迁移的是：

- 工具调用协议设计
- 工具提示词构建方式
- 容错解析器
- 工具结果回填策略
- 截断检测与续写机制
- 拒答检测和重试机制
- 配置化与测试体系

而不是：

- 原样复制 Cursor 专用文案
- 原样复制 Cursor 身份伪装语句
- 原样复制面向 Cursor `/api/chat` 的上游交互逻辑

## 当前项目现状

### DeepSeek2API 当前工具调用方式

当前 `deepseek2api` 的工具调用链路是：

1. 收到 `tools`
2. 把工具定义拼成一段 system prompt
3. 要求模型输出 OpenAI 风格的 `tool_calls` JSON
4. 再通过正则和 JSON 解析把文本转换回 `tool_calls`

当前实现位置：

- `messages_prepare()` in `app.py`
- `detect_and_parse_tool_calls()` in `app.py`
- `/v1/chat/completions` route in `app.py`
- `/anthropic/v1/messages` route in `app.py`

当前方案的问题：

- 工具协议是“靠模型自己输出一段严格 JSON”，对格式稳定性要求高
- OpenAI 路由和 Anthropic 路由各自有一套类似但不完全相同的工具逻辑，重复严重
- 解析器偏脆，主要靠正则和局部 JSON 匹配
- 缺少像 `cursor2api` 那样的截断恢复、参数修复、拒答重试、工具强制约束
- 提示词构建和响应解析混在大函数中，后续维护成本高

### Cursor2API 当前工具调用方式

`cursor2api` 的核心不是让模型吐 OpenAI `tool_calls`，而是定义自己的调用协议：

```json
```json action
{
  "tool": "ACTION_NAME",
  "parameters": {
    "param": "value"
  }
}
```
```

它的关键优势是：

- 提示词更像“工具 DSL”
- 响应解析器围绕 `json action` 代码块专门设计
- 能处理不完整代码块、字符串里包含反引号、半截 JSON
- 有 few-shot、tool_choice 约束、参数修复、拒答重试、截断续写、智能去重
- OpenAI、Anthropic、Responses 三条兼容链路共享同一套核心机制

## 完美方案的核心原则

### 原则 1

迁移“机制”，不迁移“场景伪装”。

要迁移：

- `json action` 协议
- prompt builder 结构
- parser
- argument fixer
- truncation/continuation
- retry/fallback

不要直接迁移：

- Cursor 身份相关文案
- Documentation Assistant 认知重构文案
- Cursor 上游 API 专属逻辑

### 原则 2

先模块化，再替换。

不要直接在现有 `app.py` 里继续堆更多 if/else。正确做法是先把工具相关逻辑抽成独立模块，再逐步切换路由使用新机制。

### 原则 3

双轨过渡，保留回滚能力。

迁移初期不应该直接删除当前 `tool_calls` 方案，而应该支持：

- `legacy` 模式：现有 `tool_calls` JSON 方案
- `json_action` 模式：新协议

这样可以逐步验证，不会一次性把生产可用性打穿。

### 原则 4

OpenAI 和 Anthropic 两条兼容链路必须收敛到同一套工具引擎。

如果继续保留两套独立实现，后面只会重复修 bug。

## 建议的目标架构

建议把 `deepseek2api` 的工具能力重构成下面几个模块。

### 1. Tool Prompt Builder

职责：

- 接收工具定义
- 生成统一的 `json action` 工具协议提示词
- 支持不同模式：
  - normal
  - tool_choice_any
  - tool_choice_specific
  - no_tools
- 允许插入 few-shot 示例

建议文件：

- `tool_prompt.py`

### 2. Tool Call Parser

职责：

- 从模型文本中解析 ` ```json action ` 代码块
- 支持不完整 block 的容错解析
- 支持 JSON 字符串里含反引号的情况
- 返回：
  - parsed tool calls
  - clean text
  - parse diagnostics

建议文件：

- `tool_parser.py`

### 3. Tool Argument Fixer

职责：

- 修复常见参数名偏差
- 修复智能引号
- 对字符串参数进行轻度清洗
- 为未来 fuzzy match 留接口

建议文件：

- `tool_fixer.py`

### 4. Tool Runtime Adapter

职责：

- 把客户端传来的工具定义统一转换成内部结构
- 支持 OpenAI tools 和 Anthropic tools 两种输入格式
- 把解析结果再转换回：
  - OpenAI `tool_calls`
  - Anthropic `tool_use`

建议文件：

- `tool_adapter.py`

### 5. Response Guard

职责：

- 检测拒答
- 检测工具调用是否被截断
- 检测是否需要自动续写
- 检测是否工具调用为空但应强制触发

建议文件：

- `response_guard.py`

### 6. Shared Tool Engine

职责：

- 作为 OpenAI 路由和 Anthropic 路由的统一入口
- 接收原始请求
- 插入系统提示词和 few-shot
- 调用 DeepSeek 上游
- 流式/非流式解析响应
- 输出标准结果

建议文件：

- `tool_engine.py`

## 迁移范围

## 第一层：必须迁移

- `json action` 协议
- 工具提示词构造器
- few-shot 机制
- 健壮的代码块解析器
- OpenAI 路由统一工具逻辑
- Anthropic 路由统一工具逻辑
- tool result 回填和二轮对话兼容

## 第二层：强烈建议迁移

- 参数修复器
- `tool_choice=any` 强制重试
- 截断检测
- 自动续写和去重
- 工具调用解析日志
- 配置化开关

## 第三层：评估后迁移

- thinking 抽取
- response sanitization
- refusal patterns
- adaptive budget
- smart truncation

说明：

第三层能力并非不能迁，而是它们和 `cursor2api` 的 Cursor/Claude 场景耦合更强，需要按 DeepSeek 实际输出特征重新设计，不能机械复制。

## 分阶段实施计划

## Phase 0: 建立迁移安全边界

目标：

- 不直接替换生产逻辑
- 先建立新旧双轨能力

任务：

- 在 `config.json` 新增工具策略配置，例如：
  - `tool_call_strategy`
  - `tool_call_fewshot`
  - `tool_call_retry`
  - `tool_call_auto_continue`
- 默认保留现有 legacy 行为
- 为新模块预留独立入口

交付物：

- 新配置字段
- 配置读取逻辑
- 文档更新

## Phase 1: 抽离现有工具逻辑

目标：

- 从 `app.py` 中剥离重复代码

任务：

- 把当前 OpenAI/Anthropic 路由中的工具提示词构造抽出
- 把当前工具检测和解析逻辑抽出
- 把 OpenAI 和 Anthropic 的工具结果格式化逻辑抽出

交付物：

- `tool_prompt.py`
- `tool_adapter.py`
- `tool_parser.py` 的初版

验收标准：

- 行为与现有版本基本一致
- 仅重构，不改协议

## Phase 2: 引入 json action 协议

目标：

- 建立 `cursor2api` 风格的新工具调用协议

任务：

- 新增 `build_json_action_prompt()`
- 为每个工具输出统一 DSL 说明
- 加入最少但有效的 few-shot
- 支持：
  - 多工具并行调用
  - 单工具指定调用
  - 无需工具时输出普通文本

关键注意：

- 文案必须改写为面向 DeepSeek 的通用描述
- 不能保留 Cursor 身份相关内容
- 不能保留“documentation assistant”伪装文案

交付物：

- 新版工具提示词构建器
- 新版 few-shot 生成器

验收标准：

- 模型能稳定输出 ` ```json action ` 结构
- 单工具和多工具场景都能成功触发

## Phase 3: 引入健壮解析器

目标：

- 替换现有脆弱的 `tool_calls` JSON 检测器

任务：

- 迁移并改写 `cursor2api` 的 block 扫描思想
- 解析 `json action` block
- 支持：
  - 闭合 block
  - 未闭合 block
  - JSON 内部有反引号
  - 多个 tool block
- 增加 parse diagnostics 便于日志调试

交付物：

- `parse_json_action_blocks()`
- `has_tool_calls()`
- `is_tool_call_complete()`

验收标准：

- 能正确解析复杂工具参数
- 对长文本和多工具返回不误判

## Phase 4: 统一 OpenAI 和 Anthropic 路由

目标：

- 两条兼容链路共用同一套工具引擎

任务：

- OpenAI `/v1/chat/completions` 改为调用 shared tool engine
- Anthropic `/anthropic/v1/messages` 改为调用 shared tool engine
- 输出层只保留格式转换差异

交付物：

- `tool_engine.py`
- 两个路由收敛后的统一处理流程

验收标准：

- OpenAI 与 Anthropic 在同一输入语义下得到一致的工具行为
- 不再维护两套独立的工具注入和解析逻辑

## Phase 5: 加入容错机制

目标：

- 让工具调用更稳定，不再一出问题就直接退化

任务：

- 增加参数修复器
- 增加 `tool_choice=any` 强制重试
- 增加拒答检测和重试
- 增加截断检测
- 增加自动续写和去重

交付物：

- `tool_fixer.py`
- `response_guard.py`

验收标准：

- 半截工具调用可恢复
- 空工具调用可重试
- 大参数工具调用成功率明显提升

## Phase 6: 流式与非流式一致性改造

目标：

- 解决“流式能用、非流式不稳”或相反的问题

任务：

- 流式模式下缓存并解析 `json action`
- 非流式模式下使用同一解析器
- 统一 finish reason 映射
- 保证 OpenAI 和 Anthropic 都能正确表达工具调用结束状态

验收标准：

- 流式和非流式行为一致
- 多工具调用在两种模式下都能正确返回

## Phase 7: 配置、日志、文档、测试补全

目标：

- 让这套机制可维护、可验证、可回滚

任务：

- 增加工具链路调试日志
- 在 README 中增加 `json action` 模式说明
- 增加配置说明
- 增加最小回归测试

验收标准：

- 出问题时能快速知道是提示词问题、解析器问题还是上游响应问题
- 有清晰的回滚开关

## 具体迁移映射

下面是建议从 `cursor2api` 迁移到 `deepseek2api` 的内容映射。

### 可以高优先级复用的思想

- `buildToolInstructions()` 的结构思路
- `json action` 协议
- `parseToolCalls()` 的 block 扫描思路
- `fixToolCallArguments()` 的参数修复思路
- `shouldAutoContinueTruncatedToolResponse()` 的设计思路
- continuation 去重思路

### 需要改写后再迁移的内容

- few-shot 示例文本
- system prompt 结构
- refusal patterns
- thinking 注入位置
- tool result 自然语言包装方式

### 不应直接迁移的内容

- Cursor 身份伪装文案
- Documentation Assistant 认知重构文案
- Cursor 专属 API 路径和事件流处理
- stealth-proxy
- Vercel Bot Protection 相关逻辑

## 建议新增配置

建议给 `config.json` 增加下面这些字段。

```json
{
  "tool_call_strategy": "legacy",
  "tool_call_fewshot": true,
  "tool_call_retry_on_empty": true,
  "tool_call_retry_on_refusal": true,
  "tool_call_auto_continue": false,
  "tool_call_parser": {
    "mode": "json_action",
    "fix_arguments": true
  }
}
```

字段解释：

- `tool_call_strategy`
  - `legacy`
  - `json_action`
- `tool_call_fewshot`
  - 是否启用 few-shot
- `tool_call_retry_on_empty`
  - `tool_choice=any` 或工具预期触发但未触发时是否重试
- `tool_call_retry_on_refusal`
  - 检测到拒答后是否重试
- `tool_call_auto_continue`
  - 检测到半截工具调用时是否自动续写
- `tool_call_parser.fix_arguments`
  - 是否启用参数修复

## 风险评估

### 风险 1

DeepSeek 的输出风格和 Cursor/Claude 不同，`json action` 成功率不会天然等于 `cursor2api`。

应对：

- 先双轨
- 先小范围启用
- 做 A/B 测试

### 风险 2

`app.py` 当前是单文件，直接大改极易引入回归。

应对：

- 先模块化抽离
- 再切换调用

### 风险 3

Anthropic 和 OpenAI 两条兼容路由如果不同步，会继续分叉。

应对：

- 强制共用一套 tool engine

### 风险 4

如果直接复制 `cursor2api` 的拒答和身份清洗规则，可能误伤 DeepSeek 正常回答。

应对：

- 只迁机制
- 规则库按 DeepSeek 实际响应重新采样

## 验证计划

必须覆盖下面这些场景。

### 基础场景

- 单工具调用
- 多工具并行调用
- 有文本前导再调用工具
- 工具执行后继续第二轮对话

### 兼容接口场景

- OpenAI `/v1/chat/completions`
- Anthropic `/anthropic/v1/messages`
- 流式
- 非流式

### 容错场景

- 半截 `json action`
- 工具参数含代码块
- 工具参数含大段文本
- 模型拒绝调用工具
- `tool_choice=any` 未触发工具

### 回归场景

- 无 tools 的普通对话不应退化
- 现有 DeepSeek 账号轮换不应受影响
- 会话删除逻辑不应受影响
- PoW 逻辑不应受影响

## 最终验收标准

满足下面条件，才算这次迁移真正完成。

- `deepseek2api` 已支持 `json action` 工具协议
- OpenAI 和 Anthropic 两条路由共用一套工具引擎
- 至少保留 legacy 回滚开关
- 多工具调用比当前版本更稳定
- 半截工具调用可以恢复
- 提示词和解析逻辑不再散落在多个大函数里
- README 和配置说明完整同步

## 推荐实施顺序

推荐顺序如下：

1. 抽离工具相关函数
2. 加新配置和双轨开关
3. 上 `json action` prompt builder
4. 上新 parser
5. OpenAI 路由切换
6. Anthropic 路由切换
7. 加 retry/continuation/fixer
8. 补日志和测试
9. 评估后默认切到 `json_action`

## 我对这次改造的判断

这是一次中等偏大的结构升级，不是简单功能补丁。

如果目标是“尽量完美”，正确路线一定是：

- 先重构工具链路边界
- 再迁移 `cursor2api` 的稳定机制
- 最后才做默认切换

如果跳过这一步，直接在现有 `app.py` 上粘贴 `cursor2api` 的文案和解析逻辑，最终大概率只会得到一个更复杂、但不更稳定的版本。
