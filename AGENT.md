# StudyPage Agent：配置、运行与扩展

## 接入真实模型

1. 将 .env.example 复制为 .env.local，填写 STUDY_API_KEY。文件被 Git 忽略，不发送给浏览器。进程环境变量优先。
2. 编辑 config/models.yaml：填写厂商提供的 base_url（通常以 /v1 结尾）和准确模型 ID，将 mode 改为 live。不要把密钥写进 YAML。
3. 依据实际模型窗口填写 context_window、context_budget 和 output_tokens。默认总预算 16,384，输出 2,048；计数采用保守 UTF-8 字节估计，无需下载 tokenizer。很长的中文选区可能需缩小或提高预算。
4. 运行 start.cmd，或到设置页点击“重载本地配置”。设置页可跟随文件配置，也可显式选择演示或真实 AI；显式选择会被浏览器记住。
5. 可点击“测试模型连接”，分别测试普通回答、强制工具调用和流式输出。它会调用真实 API，可能产生少量费用；普通启动不会自动调用；真实模式下新课程首批上传结束会自动尝试生成课程概况。

真实请求失败会显示错误，不会切换成演示成功。不同厂商的工具调用、流式和参数兼容性需实测。未提供真实密钥时自动化测试使用模拟模型，无法证明某个厂商的问答质量。

原文件与会话保存在本地。真实模型会收到选区、检索片段、必要历史和 Skill 指令；不会把原文件上传到托管文件搜索服务。阅读与演示模式可离线运行。

## 提示词与流程

prompts/base.md 是通用规则；课程问答、翻译、简短解释、详细解释和当前页总结各有独立模板。课程概况使用 prompts/course-overview.md 独立模板。修改后重载配置，新请求使用新版本，进行中的请求保留旧快照。无效配置保留旧版本并显示错误。

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

### 在设置页编辑系统提示词

进入设置页的“提示词管理”栏目（`#/settings/prompts`），可查看通用规则、课程问答、翻译、简短解释、详细解释、总结、课程概况七份当前提示词。API Key、运行模式及连接测试位于“常规设置”栏目。切换栏目保留未保存的提示词草稿，刷新页面会重新读取已保存内容。直接编辑文本框并点击对应保存按钮，内容写入本地 prompts Markdown 文件并立即重载，新请求使用更新版本；进行中的生成保持原版本。提示词长期保存，重启后仍可读取。每份提示词最多 20,000 字符且不能为空。

划词后进入“解释”，默认给出简短定义。点击回复下方“详细解释”，将使用独立的 explain_detail 配置与 prompts/explain-detail.md 重新生成细致讲解，可包含一个小例子和符号说明；不会把简短解释的两句限制带入该会话。之后的追问与重试沿用详细解释；切换弹窗标签会保留当前结果，新选区恢复默认简短解释。详细解释可保存笔记或转入主对话，文件选区检索仅限该文件；消息与笔记选区可按需检索同课程资料。演示模式只返回明确标记的词典内容，不生成假详细回答。

“重新载入提示词”可撤销未保存的编辑；放弃编辑前会提示确认。若其他窗口保存过配置，或文件在编辑器中被修改，保存会提示冲突，避免覆盖新内容；外部文件修改需先重载本地配置，再重新载入提示词。工具权限和课程隔离仍由代码与配置控制。

### 在设置页保存 API Key

设置页的“AI API Key”区域支持选择模型配置、输入并保存密钥。密钥保存到项目内被 Git 忽略的 `.env.local`，不回显、不存入浏览器；保存后新请求立即使用新密钥，进行中的请求保持原配置。保存不会调用模型 API，也不会自动切换运行模式。

接口地址与模型名称仍在 `config/models.yaml` 配置。保存后可选择“真实 AI”，使用“测试模型连接”进行显式 API 测试。如果系统环境变量已经提供该模型的密钥，页面会提示先移除该变量，避免本地保存被环境变量覆盖。

## 通用选区来源与课程概况扩展

`TextOperationSource` 位于 domain。service/text_sources.py 校验归属、来源和字符位置并截取至多 2,000 字符的局部背景；消息/笔记不会递归展开关联记录或把整段聊天交给模型。前端 services/text-sources.js 提供来源注册表及阅读器、消息、笔记适配器。新增正文只需注册适配器，操作控制器不访问 PDF.js。前端偏移用 Unicode 码点，与 Python 一致。

Agent 运行接口增加 `source`，例如 `{"kind":"message","id":"记录ID","start":0,"end":3,"text_field":"content"}`；note 可选 body 或 selected_text，document 使用 id/page_start/page_end。selected_text 单独传入。旧 document_id/page_start/page_end 继续可用；新旧字段冲突会拒绝。笔记接口同样支持 source，可附完成回复的 run_id 保留其已验证引用；课程、来源和选区必须一致。整条完成回复保存笔记使用 start=end=0、空选区与正文。

每轮在 service 固定概况版本，runtime 使用独立 `<course_context>`、`<local_context>` 和 `<materials>` 块；仅本课程背景可注入，补充说明不直接注入。恢复会话时移除历史请求背景，避免累积多个概况。消息/笔记及课程背景不是引用证据，原始资料仍需经专用工具读取和验证。

课程概况由 service/course_overview.py 协调，dp/overview_store.py 原子保存、版本比对与中断恢复，dp/overview_model.py 通过模型网关执行有预算的分批归纳与合并，不启用 Skill/MCP/自主工具。仅资料指纹、提示词和模型配置版本匹配的批次可复用。唯一内容文件是课程目录中的 context/course-overview.json，不另存 Markdown。

`config/agents.yaml` 的 course_overview 未显式指定模型时跟随课程问答模型；可修改模型、提示词、timeout（默认300秒，最多1800）及 max_model_calls（默认30，最多200）。单批输入保守估计不超过可用预算的一半；默认 JSON 解析与一次修复，可在支持的模型配置上显式填写 structured_output: json_schema。结构或长度校验失败不发布。

接口：

- GET/PUT `/api/courses/{id}/overview`：读取或版本化保存，PUT 必须带 expected_version。
- POST `/api/courses/{id}/overview/runs`：mode 可选 demo/live；initial=true 表示首批上传后的幂等尝试。
- GET `/api/courses/{id}/overview/runs/{run_id}`：任务阶段、覆盖及结果状态。
- POST `/api/courses/{id}/overview/runs/{run_id}/cancel`：停止任务并保留旧概况。

自动测试包含所有新来源、旧库迁移、SSE/API、概况版本冲突、无正文与缺密钥、取消超时、分批覆盖、缓存恢复及提示词保存。浏览器启动隔离的 tests/browser_server.py 后运行 `node tests/browser_text_tools.cjs`；它验证首批部分成功、自动尝试、手动编辑、消息/笔记划词、文件切换后来源不变、来源跳转和窄屏弹窗。

可选真实模型评估：` .venv/Scripts/python.exe scripts/evaluate_text_operations.py --live `。此命令会调用配置的 API、产生费用；默认不执行，自动化测试也不会运行它。合成课程及报告位于 `.cache/evaluations/<批次>/`，报告包含格式合规率、术语准确率和逐项原始结果，需人工复核。它不替换模型回答；失败后应修订提示词并复测。
