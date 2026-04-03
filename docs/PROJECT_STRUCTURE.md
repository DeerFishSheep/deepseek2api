# 项目结构说明

## 当前结构

```text
deepseek2api/
├─ app.py
├─ config.json
├─ tooling/
│  ├─ __init__.py
│  ├─ adapter.py
│  ├─ config.py
│  ├─ fixer.py
│  ├─ guard.py
│  ├─ parser.py
│  └─ prompt.py
├─ templates/
└─ docs/
```

## 模块职责

### 根目录

- [`app.py`](../app.py)：当前主入口，包含路由、DeepSeek 请求、会话逻辑、流式适配
- [`config.json`](../config.json)：运行配置
- [`Dockerfile`](../Dockerfile)：容器构建
- [`docker-compose.yml`](../docker-compose.yml)：本地 compose 编排

### `tooling/`

- [`tooling/adapter.py`](../tooling/adapter.py)：协议适配层，负责 OpenAI / Anthropic tools 转换
- [`tooling/config.py`](../tooling/config.py)：工具相关配置读取
- [`tooling/fixer.py`](../tooling/fixer.py)：参数与引号修复
- [`tooling/guard.py`](../tooling/guard.py)：重试、拒答识别、自动续写判定
- [`tooling/parser.py`](../tooling/parser.py)：`json action` / legacy 解析器
- [`tooling/prompt.py`](../tooling/prompt.py)：工具提示词和 `tool_choice` 标准化

### `docs/`

- [`docs/TOOLS_SUPPORT.md`](TOOLS_SUPPORT.md)：工具调用说明
- [`docs/CURSOR2API_MIGRATION_PLAN.md`](CURSOR2API_MIGRATION_PLAN.md)：迁移方案与设计记录
- 当前文档定位是“设计说明 + 使用说明”，不承载运行时代码逻辑

## 为什么先做这层整理

已确认：

- `app.py` 仍然是大文件
- 但工具调用部分已经具备明确边界
- 先把 `tooling/` 抽出来，能降低后续继续拆分 `app.py` 的风险

这一步的收益是：

- 先把最容易扩散的工具逻辑收口
- 让 OpenAI / Anthropic 两条链路共用同一批模块
- 后续更容易继续提炼 `services/`、`routes/`、`clients/`

## 后续建议的清洗顺序

建议按这个顺序继续拆：

1. `routes/`
   把 OpenAI 和 Anthropic 路由从 `app.py` 中拆出
2. `services/`
   把消息预处理、会话管理、流式收敛等逻辑下沉
3. `clients/`
   把 DeepSeek 上游 HTTP 调用抽成独立客户端
4. `models/` 或 `schemas/`
   再考虑是否需要补响应结构体和配置结构体

不建议一开始就全量重构，因为当前项目仍是单文件起家，直接大改容易引入回归。
