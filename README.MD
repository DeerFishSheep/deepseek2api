# DeepSeek2API

[![](https://img.shields.io/github/license/DeerFishSheep/deepseek2api.svg)](LICENSE)
![](https://img.shields.io/github/stars/DeerFishSheep/deepseek2api.svg)
![](https://img.shields.io/github/forks/DeerFishSheep/deepseek2api.svg)

一个面向 DeepSeek Web 侧能力的兼容代理，提供：

- OpenAI 风格的 `/v1/chat/completions`
- Anthropic 风格的 `/anthropic/v1/messages`
- 多账号轮换、会话清理、流式输出
- 增强后的工具调用链路：默认使用 `json action` 协议，并保留 legacy 兼容回退

## 免责声明

这是基于逆向行为的兼容代理，不保证长期稳定，也不建议对外提供商业服务。

- 已确认：项目当前以研究、学习、自用为主要目标。
- 待验证：DeepSeek 上游行为、风控策略、网页接口细节都可能随时间变化。
- 建议：如果你需要稳定生产能力，优先考虑官方 API。

## 这份增强版做了什么

相较于上游版本，这个仓库当前额外增强了工具调用能力：

- 默认工具策略从原来的纯 `tool_calls` 提示词方案升级为 `json_action`
- 新增 `tooling/` 模块，拆出 prompt、parser、adapter、guard、fixer、config
- 支持 `tool_choice=any` / 指定工具调用的约束提示
- 支持空工具调用重试、工具拒绝纠偏、半截 `json action` 自动续写
- OpenAI 和 Anthropic 两条兼容链路共用一套工具解析逻辑

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/DeerFishSheep/deepseek2api.git
cd deepseek2api
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 `config.json`

示例：

```json
{
  "keys": [
    "key1",
    "key2"
  ],
  "accounts": [
    {
      "email": "example1@example.com",
      "password": "password1",
      "token": ""
    }
  ],
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

字段说明：

- `keys`：对外暴露给客户端使用的 API Key 列表
- `accounts`：DeepSeek 账号列表，支持多账号轮换
- `tool_call_strategy`：`json_action` 或 `legacy`
- `tool_call_fewshot`：是否在提示词中注入简短工具调用示例
- `tool_call_retry_on_empty`：要求调用工具但模型未调用时是否自动重试
- `tool_call_retry_on_refusal`：模型误判“不能用工具”时是否纠偏重试
- `tool_call_auto_continue`：`json action` 被截断时是否自动续写
- `tool_call_retry_max_attempts`：最大重试次数
- `tool_call_parser.fix_arguments`：是否自动修复常见工具参数格式问题

### 4. 启动服务

```bash
python app.py
```

默认监听端口为 `5001`。

## Docker 部署

### Docker

```bash
docker build -t deepseek2api:local .
docker run -d -p 5001:5001 -v "$(pwd)/config.json:/app/config.json" --name deepseek2api deepseek2api:local
```

### Docker Compose

当前仓库的 [`docker-compose.yml`](docker-compose.yml) 已调整为构建本地增强版镜像：

```bash
docker compose up --build -d
```

## 接口概览

已确认当前服务暴露以下主要接口：

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/chat/stop_stream`
- `GET /anthropic/v1/models`
- `POST /anthropic/v1/messages`
- `POST /anthropic/v1/messages/count_tokens`
- `POST /anthropic/v1/messages/stop_stream`

### OpenAI 兼容接口

基础地址：

```text
http://127.0.0.1:5001/v1
```

示例请求：

```json
{
  "model": "deepseek-chat",
  "messages": [
    {
      "role": "user",
      "content": "你好，介绍一下你自己。"
    }
  ],
  "stream": false
}
```

可用模型别名：

- `deepseek-chat`
- `deepseek-reasoner`
- `deepseek-chat-search`
- `deepseek-reasoner-search`

### Anthropic 兼容接口

基础地址：

```text
http://127.0.0.1:5001/anthropic/v1
```

当前模型列表接口会返回以下兼容模型名：

- `claude-sonnet-4-20250514`
- `claude-sonnet-4-20250514-fast`
- `claude-sonnet-4-20250514-slow`

## Tools 支持

当前增强版默认启用 `json_action` 工具协议，但对客户端仍然保持标准兼容：

- OpenAI 客户端传入 `tools`，收到标准 `tool_calls`
- Anthropic 客户端传入 `tools`，收到标准 `tool_use`
- 服务内部会把模型输出的 `json action` 块解析并重新适配为兼容响应

详细说明见：

- [Tools 支持说明](docs/TOOLS_SUPPORT.md)
- [迁移计划与设计记录](docs/CURSOR2API_MIGRATION_PLAN.md)

## 项目结构

当前已经完成一轮轻量结构化整理：

- [`app.py`](app.py)：主入口与路由
- [`tooling/`](tooling)：工具调用相关模块
- [`templates/`](templates)：页面模板
- [`docs/`](docs)：项目文档与迁移说明

如果你要继续清洗代码结构，建议下一步优先拆分：

- 路由层
- DeepSeek 上游客户端
- 会话管理与账号轮换
- SSE / 流式适配逻辑

## 验证方式

已确认当前仓库可通过基础编译检查：

```bash
py -3 -m py_compile app.py tooling/__init__.py tooling/adapter.py tooling/config.py tooling/fixer.py tooling/guard.py tooling/parser.py tooling/prompt.py
py -3 -m compileall .
```

如果你修改了代码，建议至少重复一次这两步。

## 相关文档

- [Tools 支持说明](docs/TOOLS_SUPPORT.md)
- [项目结构说明](docs/PROJECT_STRUCTURE.md)
- [Cursor2API 迁移计划](docs/CURSOR2API_MIGRATION_PLAN.md)

## 致谢

部分思路和实现参考了这些项目：

- [iidamie/deepseek2api](https://github.com/iidamie/deepseek2api)
- [LLM-Red-Team/deepseek-free-api](https://github.com/LLM-Red-Team/deepseek-free-api)
- [7836246/cursor2api](https://github.com/7836246/cursor2api)
