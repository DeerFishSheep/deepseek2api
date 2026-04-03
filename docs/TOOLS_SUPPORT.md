# Tools 支持说明

## 概览

当前增强版 `deepseek2api` 已支持：

- OpenAI 风格 `tools` 输入与 `tool_calls` 输出
- Anthropic 风格 `tools` 输入与 `tool_use` 输出
- 默认 `json_action` 工具协议
- `legacy` 回退策略
- 空调用重试、拒答纠偏、截断续写、参数修复

这里有一个重要区别：

- 对客户端来说，它仍然是标准 OpenAI / Anthropic 接口
- 对 DeepSeek 模型内部提示和解析来说，它现在优先使用 `json action` 协议

## 当前工具调用策略

### 1. `json_action`

这是当前默认策略。

服务会在系统提示中注入工具目录和调用规则，要求模型在需要调用工具时输出如下格式：

````text
```json action
{
  "tool": "get_weather",
  "parameters": {
    "location": "Beijing"
  }
}
```
````

代理层会扫描这些 fenced block，解析后再转换成：

- OpenAI 响应中的 `tool_calls`
- Anthropic 响应中的 `tool_use`

### 2. `legacy`

这是历史兼容策略。

模型会被要求直接输出 OpenAI 风格的 `tool_calls` JSON，代理层再从文本中回解析。这个模式仍然保留，但不再是默认推荐方案。

## 为什么默认推荐 `json_action`

已确认当前增强版把工具链路拆成了独立模块：

- [`tooling/prompt.py`](/e:/Users/Lyy/Desktop/服务器项目/deepseek2api/iidamie-deepseek2api/tooling/prompt.py)
- [`tooling/parser.py`](/e:/Users/Lyy/Desktop/服务器项目/deepseek2api/iidamie-deepseek2api/tooling/parser.py)
- [`tooling/adapter.py`](/e:/Users/Lyy/Desktop/服务器项目/deepseek2api/iidamie-deepseek2api/tooling/adapter.py)
- [`tooling/guard.py`](/e:/Users/Lyy/Desktop/服务器项目/deepseek2api/iidamie-deepseek2api/tooling/guard.py)
- [`tooling/fixer.py`](/e:/Users/Lyy/Desktop/服务器项目/deepseek2api/iidamie-deepseek2api/tooling/fixer.py)

相比旧版方案，它多了几层稳定性处理：

- 更明确的工具调用 DSL
- 专门的 block 扫描解析器
- 工具参数修复
- `tool_choice=any` 空调用重试
- “工具不可用”类误判回复纠偏
- 半截 `json action` 自动续写

## 配置项

配置文件示例见 [`config.json`](/e:/Users/Lyy/Desktop/服务器项目/deepseek2api/iidamie-deepseek2api/config.json)。

与 tools 相关的字段：

```json
{
  "tool_call_strategy": "json_action",
  "tool_call_fewshot": true,
  "tool_call_retry_on_empty": true,
  "tool_call_retry_on_refusal": true,
  "tool_call_auto_continue": true,
  "tool_call_retry_max_attempts": 1,
  "tool_call_parser": {
    "fix_arguments": true
  }
}
```

含义如下：

- `tool_call_strategy`：工具协议策略，支持 `json_action` 和 `legacy`
- `tool_call_fewshot`：是否注入简短示例帮助模型遵循格式
- `tool_call_retry_on_empty`：要求工具调用但模型没调时是否自动重试
- `tool_call_retry_on_refusal`：模型回复“不能使用工具”时是否自动纠偏
- `tool_call_auto_continue`：输出半截 `json action` 时是否自动续写
- `tool_call_retry_max_attempts`：重试次数上限
- `tool_call_parser.fix_arguments`：是否自动修复常见参数问题

## OpenAI 兼容示例

请求：

```python
import requests

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的天气",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string"}
                },
                "required": ["location"]
            }
        }
    }
]

resp = requests.post(
    "http://127.0.0.1:5001/v1/chat/completions",
    json={
        "model": "deepseek-chat",
        "messages": [
            {"role": "user", "content": "帮我查一下北京天气"}
        ],
        "tools": tools
    }
)

print(resp.json())
```

模型如果决定调用工具，返回给客户端的仍然是标准 `tool_calls`：

```json
{
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [
          {
            "id": "call_001",
            "type": "function",
            "function": {
              "name": "get_weather",
              "arguments": "{\"location\":\"北京\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ]
}
```

## Anthropic 兼容示例

请求：

```python
import requests

tools = [
    {
        "name": "get_weather",
        "description": "获取指定城市的天气",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string"}
            },
            "required": ["location"]
        }
    }
]

resp = requests.post(
    "http://127.0.0.1:5001/anthropic/v1/messages",
    json={
        "model": "claude-sonnet-4-20250514",
        "messages": [
            {"role": "user", "content": "帮我查一下北京天气"}
        ],
        "tools": tools,
        "max_tokens": 1024
    }
)

print(resp.json())
```

返回中会适配成 `tool_use` block。

## 流式模式说明

已确认当前增强版对流式 tools 做了额外处理：

- 不会把原始 `json action` DSL 直接透传给 OpenAI 客户端
- 会先缓存模型输出
- 在结尾统一解析
- 再转换成标准 `tool_calls` 或普通文本流结果

这意味着客户端看到的依然是兼容协议，不需要理解内部 `json action` 格式。

## 客户端完整调用流程

1. 客户端发起请求，并声明 `tools`
2. 服务把工具目录转成内部提示词
3. DeepSeek 模型在需要时输出 `json action`
4. 服务解析并转换成标准工具调用响应
5. 客户端执行工具
6. 客户端把工具结果回填给服务继续对话

## 当前已知限制

- 已确认：工具调用仍然属于提示词诱导和文本解析，不是 DeepSeek 原生 function calling
- 待验证：不同 DeepSeek 模型版本对 `json action` 的遵循度可能不同
- 待验证：复杂多工具链、超长上下文、极端截断场景下仍可能需要继续优化
- 建议：客户端仍然自己做参数校验，不要把模型生成参数当作绝对可信输入

## 相关文件

- [`app.py`](/e:/Users/Lyy/Desktop/服务器项目/deepseek2api/iidamie-deepseek2api/app.py)
- [`tooling/prompt.py`](/e:/Users/Lyy/Desktop/服务器项目/deepseek2api/iidamie-deepseek2api/tooling/prompt.py)
- [`tooling/parser.py`](/e:/Users/Lyy/Desktop/服务器项目/deepseek2api/iidamie-deepseek2api/tooling/parser.py)
- [`tooling/adapter.py`](/e:/Users/Lyy/Desktop/服务器项目/deepseek2api/iidamie-deepseek2api/tooling/adapter.py)
- [`tooling/guard.py`](/e:/Users/Lyy/Desktop/服务器项目/deepseek2api/iidamie-deepseek2api/tooling/guard.py)
- [`docs/CURSOR2API_MIGRATION_PLAN.md`](/e:/Users/Lyy/Desktop/服务器项目/deepseek2api/iidamie-deepseek2api/docs/CURSOR2API_MIGRATION_PLAN.md)
