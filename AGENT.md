# StudyPage Agent：配置、运行与扩展

## 接入真实模型

1. 将 .env.example 复制为 .env.local，填写 STUDY_API_KEY。文件被 Git 忽略，不发送给浏览器。进程环境变量优先。
2. 编辑 config/models.yaml：填写厂商提供的 base_url（通常以 /v1 结尾）和准确模型 ID，将 mode 改为 live。不要把密钥写进 YAML。
3. 依据实际模型窗口填写 context_window、context_budget 和 output_tokens。默认总预算 16,384，输出 2,048；计数采用保守 UTF-8 字节估计，无需下载 tokenizer。很长的中文选区可能需缩小或提高预算。
4. 运行 start.cmd，或到设置页点击“重载本地配置”。设置页可跟随文件配置，也可显式选择演示或真实 AI；显式选择会被浏览器记住。
5. 可点击“测试模型连接”，分别测试普通回答、强制工具调用和流式输出。它会调用真实 API，可能产生少量费用；启动不会自动调用。

真实请求失败会显示错误，不会切换成演示成功。不同厂商的工具调用、流式和参数兼容性需实测。未提供真实密钥时自动化测试使用模拟模型，无法证明某个厂商的问答质量。

原文件与会话保存在本地。真实模型会收到选区、检索片段、必要历史和 Skill 指令；不会把原文件上传到托管文件搜索服务。阅读与演示模式可离线运行。

## 提示词与流程

prompts/base.md 是通用规则，其余四个文件分别负责问答、翻译、解释和当前页总结。修改后重载配置，新请求使用新版本，进行中的请求保留旧快照。无效配置保留旧版本并显示错误。

config/agents.yaml 支持选择模型、提示词、已注册流程、工具白名单和 Skill。默认超时 120 秒、最多 6 次业务工具调用、24 个图执行步骤；模型调用另有限制。严格流程由注册模块实现，YAML 不执行任意代码。

主对话按课程共享；选区翻译与解释分别使用自己的持久会话。演示历史不自动进入真实模型记忆。旧历史压缩不删除页面记录；模型历史保留完整工具消息结构。以前工具结果会省略，必要时重新读取课程资料验证来源。

数据库：library.db 保存业务记录、FTS5 索引和回复来源；agent-sessions.db 保存内部消息、摘要、状态及卸载文件；checkpoints.db 保存 LangGraph 运行中状态。失败、取消不提交半完成消息，重启将未完成运行标为中断。不同线程并发、同线程串行。

首次启动进行 v2 迁移，备份到 data/backups/agent-v2/library.db，并补建旧资料索引。重复启动不会重复备份，不修改原文件。备份整个项目数据前先停止服务。

## Skill、MCP 和插件

示例 Skill 在 skills/course-concepts。Deep Agents 先发现描述，按需读取 SKILL.md 与 Markdown 参考资料；首版不执行 Skill 脚本。模型只拥有虚拟状态的只读文件工具，没有通用磁盘访问、shell、资料写入和自动委派。

config/mcp.json 支持本地 stdio 和远程 HTTP。{python} 替换为项目解释器，{root} 替换为项目根目录。示例 examples/terminology_mcp.py 是离线、只读的术语工具。每次连接和调用最多 15 秒，会在请求结束时关闭会话和子进程。

MCP 必须指定工具白名单；白名单应只包含你确认只读的工具。程序无法证明任意第三方 MCP 服务没有副作用。密钥不会作为工具参数交给 MCP。修改连接后重载配置，新请求使用新设置。

plugins/academic-helper/plugin.yaml 提供示例插件。enabled 控制其 Skill 和 MCP；profiles 可覆盖现有功能配置。版本采用 x.y.z；多个插件覆盖同一功能时，后者禁用并显示错误。无效插件不阻止其他插件。插件不自动下载依赖或执行任意代码。

## 开发扩展

- domain 定义 AgentRequest、RunEvent、RunContext 和端口；不引用框架类型。
- service 负责课程隔离、上下文选择、引用校验、并发与取消、结果保存。
- dp 实现模型、框架、检索、配置、存储和 MCP；api 仅处理请求及 SSE。
- 新模型：在 RegisteredModelGateway.register 注册工厂，再把适配器名称交给 LocalProfileRegistry 校验。
- 新流程：在 LearningRuntime.register 注册异步事件生成器，配置 workflow 选择该名称。直接流程和 Deep Agents 流程使用相同服务边界。
- 新工具：通过 runtime.tools.register 注册工厂；工厂接收课程绑定的 RunContext。工具需要自行使用 context.tools.count 控制次数，并遵守课程隔离。新增工具名称加入配置校验集合，功能白名单决定是否启用。
- 替换检索：实现 Retriever 接口。当前使用 FTS5、trigram 和短词查询；没有 embedding 或向量数据库，跨语言匹配由 Agent 改写关键词改善。

配置重载会验证模型、预算、流程、工具、插件和路径，状态接口不返回密钥。所有框架版本已锁定；升级后应运行工具白名单和真实工具循环测试。

## 接口

- POST /api/courses/{id}/agent/runs：字段为 action、question、可选 document_id/page_start/page_end/selected_text、session_id、persist、mode。主对话 persist=true，弹窗 persist=false。
- SSE 返回 start、tool、delta、citations、done、error、cancelled。run ID 在 start 中返回；done 为最终、经过来源校验的完整答案，应替换前端增量文本。
- POST /api/courses/{id}/agent/runs/{run_id}/cancel：停止运行。
- POST /api/courses/{id}/agent/runs/{run_id}/transfer：复制完成回复到主对话，不重新生成；重复调用不重复写入。
- GET /api/agent/status：模式、模型是否配置、插件与 MCP 状态，不返回密钥。
- POST /api/agent/config/reload：验证并重载。
- POST /api/agent/diagnose：显式调用真实 API 检查兼容性，可能收费。

引用只接受本轮实际读取且仍存在的片段 ID。验证不代表模型答案一定正确。大页面可能只提供部分片段，回答应注明范围；无正文页不生成假总结。每次搜索最多 6 个片段，每次读页最多 3 页。

## 验证

运行 .venv/Scripts/python.exe -m unittest discover -s tests -v；运行 node --test tests/frontend_state.mjs tests/frontend_agent.mjs。

离线接口回归运行 .venv/Scripts/python.exe tests/offline_check.py，使用隔离的 .cache 数据并阻止外部网络。

可选浏览器测试：将 Playwright 库安装在 .cache/ui-test，使用现有 Edge，不另下载浏览器。运行 .venv/Scripts/python.exe tests/browser_server.py（8002，隔离数据、模拟模型），另一个终端运行 node tests/browser_agent.cjs。截图位于 .cache。正常启动始终使用 start.cmd，不能使用测试服务器。

### 在设置页保存 API Key

设置页的“AI API Key”区域支持选择模型配置、输入并保存密钥。密钥保存到项目内被 Git 忽略的 `.env.local`，不回显、不存入浏览器；保存后新请求立即使用新密钥，进行中的请求保持原配置。保存不会调用模型 API，也不会自动切换运行模式。

接口地址与模型名称仍在 `config/models.yaml` 配置。保存后可选择“真实 AI”，使用“测试模型连接”进行显式 API 测试。如果系统环境变量已经提供该模型的密钥，页面会提示先移除该变量，避免本地保存被环境变量覆盖。
