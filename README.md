# df mcp

给 AI 使用的本地团队文件读取工具，Skill 名称为 **`df-mcp`**，界面名称为 **df mcp**；GitHub 仓库仍使用 `team-drive-mcp`。架构：**Skill + MCP + SQLite 增量索引**。优先保证来源、版本和读取范围可核查，再优化定位速度。所有附带业务数据均为 **SIMULATED / 完全虚构**。

- [完整中文开发方案](docs/TEAM_AGENT_DEVELOPMENT_PLAN.md)
- [Skill 操作规范](skills/df-mcp/SKILL.md)
- [验证记录与限制](docs/VALIDATION.md)
- [Windows 只读边界与可选隔离部署](docs/WINDOWS_READ_ONLY.md)
- [10 个固定评估任务](tests/evaluation.xml)

## 已实现的范围

- 本地 stdio MCP，9 个结构化工具；不调用模型 API、不访问网络。
- SQLite 文件清单与关键词索引，支持中文短词、项目代号及配置别名。
- TXT、Markdown、CSV、TSV、XLSX、DOCX、PPTX、文字 PDF。
- 启动扫描、运行期间定期增量核对、删除失效、失败记录和强制重试。
- 分页、结构导航、原文定位、读取前 SHA256 版本校验、受控 JSONL 导出。
- 安装时选择并确认读取目录；源文件只读，索引、日志、临时解析文件及导出与源目录分离。
- 授权根目录边界、符号链接/Windows junction 与 reparse 路径拒绝、压缩文件/XML 限制、超时、明确错误。

**运行平台：Windows、macOS / Linux，Node.js >=22，Python >=3.9。** Windows 本版面向固定本地磁盘上的普通目录，支持中文及空格路径；不支持 UNC/网络映射盘、可移动盘、设备路径、junction、符号链接及其他 reparse 路径。目标为 Windows 10/11；自动测试的实际环境与结果见验证记录，不能据此宣称所有公司电脑已经验收。

**当前未实现：** SharePoint 登录与下载、多用户身份权限、OCR、向量检索、原始文件下载工具、模型自我训练、无人值守云端部署。没有真实团队资料，也没有公司 PPT 模板。

## 安装：先选择允许读取的文件夹

把仓库与真实资料放在**互不包含的独立目录**。安装 Node.js 22+ 和 Python 3.9+，进入仓库目录。在 Windows PowerShell、macOS 或 Linux 终端均可执行：

```sh
npm ci --ignore-scripts
npm run setup
npm run install:skill
```

`setup` 在仓库 `.venv` 安装 Python 依赖、编译 TypeScript，然后询问读取哪个文件夹。Windows 可通过文件夹选择窗口选取，也可按提示输入路径。向导展示读取目录与独立状态目录，确认后才保存配置；取消不保存新配置。它不在源目录创建测试文件，也不修改源目录权限。**索引在 MCP 客户端启动服务后才开始**，安装配置本身不读取整库正文。

无需模型 API key 或数据库服务器。Windows 安装脚本优先查找 `py -3`，再尝试可用的 `python`；系统商店跳转别名不作为可用解释器。支持与构建步骤遇到错误时应先解决该错误，不能把未成功的安装当作可用服务。

Skill 安装到个人 Codex 技能目录，名称为 `df-mcp`。同名目标或旧 `team-drive-read` 已存在时默认拒绝改动；明确更新或迁移旧 `team-drive-read` 可执行 `npm run install:skill -- --replace`，脚本先备份原 Skill 到 Codex 配置目录中的 `skill-backups/`，再安装。Skill 只包含操作规范，MCP 连接按下一节配置。

### 配置位置与后续换目录

默认状态基目录：

| 平台 | 默认位置 |
|---|---|
| Windows | `%LOCALAPPDATA%\df-mcp` |
| macOS | `~/Library/Application Support/df-mcp` |
| Linux | `$XDG_STATE_HOME/df-mcp`，未设置时为 `~/.local/state/df-mcp` |

每个源目录使用独立的 `profiles/<root-hash>/config.json` 与 `profiles/<root-hash>/state/`。向导会输出完整配置路径。配置、正文缓存、数据库、日志和导出按源资料的敏感程度管理，不放在源目录、同步共享盘或公开 Git 仓库中。

换目录时运行 `npm run configure`，重新选择并确认，然后用向导给出的配置路径更新 MCP 连接。不会原地把旧索引绑定到新来源，也不会删除旧配置或资料。MCP 工具本身不能更改读取目录。

已明确路径时可非交互配置，例如 Windows PowerShell：

```powershell
npm run configure -- --root 'D:\团队资料' --yes
```

`--yes` 必须与明确的 `--root` 同用，表示确认该目录。可用 `--state-dir '<独立状态基目录>'` 自定义状态基目录；向导要求源目录、状态基目录与安装目录两两不重叠，任何一个都不能包含另一个。真实资料应放在程序目录外；仓库内的合成示例仅通过专用示例配置使用，不经过真实资料安装向导。无交互终端且未给出 `--root` 会失败，不会默认扫描主目录或示例库。

## 配置 MCP 客户端

Windows PowerShell，在仓库目录执行，将 `$config` 替换成向导显示的配置文件绝对路径：

```powershell
$repo = (Get-Location).Path
$config = '<向导输出的配置文件绝对路径>'
codex mcp add df_mcp -- node (Join-Path $repo 'dist/index.js') --config $config
```

macOS / Linux：

```sh
codex mcp add df_mcp -- node "$PWD/dist/index.js" --config '<向导输出的配置文件绝对路径>'
```

这里的 `df_mcp` 是客户端连接名称；Skill 仍为 `$df-mcp`，工具名保留 `team_drive_` 前缀兼容现有调用。旧版本用户应先关闭旧会话，在客户端移除旧 `team_drive` 连接，再添加新连接，避免重复启动同一状态目录。其他支持 stdio 的客户端参考 [examples/mcp.json](examples/mcp.json)，替换路径占位符。启动新会话，让客户端发现 Skill 和工具。

同一 `state_dir` 只允许一个活跃服务进程。多窗口或多客户端应先关闭旧连接，或使用各自独立的状态配置。客户端会启动并保持 stdio 进程；不要同时手动运行另一个 `npm start`。如确需独立启动，必须明确提供 `npm start -- --config '<配置路径>'`，服务没有隐式默认源目录，也不会在协议连接中弹出选择框。

示例请求：

```text
使用 $df-mcp 查指定资料目录里本月的正式预算及可用金额，说明口径并引用单元格；缺少资料时明确说明。
```

AI 应先检查索引状态，区分正式资料与草稿，读取证据，再用确定性程序计算。搜索结果不能证明业务数据完整。

### 从 0.1 升级或重建缓存

0.2 加强了源目录身份绑定与数据库文件安全检查，不直接复用 0.1 的 WAL 索引。出现 `STATE_REBUILD_REQUIRED`、`STATE_ROOT_MISMATCH` 或异常中断后的数据库错误时，先关闭旧 MCP 会话，再运行配置向导并指定**新的状态基目录**：

```powershell
npm run configure -- --root 'D:\团队资料' --state-dir 'D:\df-mcp-state-v02' --yes
```

用新输出的配置路径更新 MCP 连接，让服务重新索引。仅对同一来源重复 `configure` 会找到原 profile，不能代替新状态目录；旧配置和缓存会保留，不自动删除。这里的 `D:` 路径是示例，应替换为本机允许的普通本地目录。

索引是可重建缓存，不是资料备份。0.2 使用单个持久 SQLite 连接、锁串行化访问及内存回滚日志，避免创建 WAL、SHM 或磁盘回滚日志旁文件；异常退出或断电可能使索引损坏，此时使用新状态目录重建。源文件仍保持只读。中断后遗留的临时文件不递归自动清理，确认旧服务已停止后可按本机维护流程处理旧状态目录。

### 只读的含义

源文件仅以读取权限打开，不提供修改、删除、重命名、移动或更改权限的 MCP 接口。解析快照、索引和生成结果写到独立状态目录。应用清理与 Skill 迁移不处理源资料。Windows 为固定目录身份而持有的句柄可能暂时阻止目录重命名或移除；需要整理源目录时先关闭服务。

这些保障约束本 MCP，**不能撤销 AI 宿主其他终端或文件工具的写权限**。需要操作系统强制只读时，由 IT 配置受限账户或隔离环境；普通安装不改变源目录 ACL。详见 [Windows 只读部署](docs/WINDOWS_READ_ONLY.md)。

Windows 不支持直接读取 OneDrive cloud reparse 文件：即使已经下载，有些文件仍可能被识别为云文件而跳过。在线占位文件不自动下载。当前请使用获准资料在普通、非同步本地文件夹中的副本；被排除或占用的文件会形成覆盖缺口，不能当作已读取。

## 测试与模拟演示

不配置个人目录、只构建并测试：

```sh
npm run setup -- --skip-config
npm test
npm run test:installer
npm run test:mcp
```

测试使用隔离临时目录和虚构资料。`--skip-config` 只跳过目录配置，不创建可用的个人读取连接。已有依赖和编译结果时可直接运行测试。

`npm run demo` 显式启动模拟目录的 stdio 服务；它不提供聊天界面，需 MCP 客户端发送协议请求。也可将客户端 `--config` 指向仓库 `examples/config.sample.json`，用 `$df-mcp` 查询样本。演示配置使用独立的 `.local/sample-v02-state/`，不会自动替换你的正式配置或复用 0.1 旧演示缓存。

## 工具与完整性

| 工具 | 用途 |
|---|---|
| `team_drive_status` | 覆盖范围、状态、限制、索引更新时间 |
| `team_drive_list` | 分页列出文件，包含失败/不支持的条目 |
| `team_drive_search` | 按名称与正文关键词发现候选；结果须回查 |
| `team_drive_inspect` | 校验版本，分页导航章节/工作表/页面结构 |
| `team_drive_read` | 按工作表/行范围/PDF页/幻灯片筛选分段，支持版本锁定与续读 |
| `team_drive_export` | 将指定版本全部已解析片段导出到受控 JSONL |
| `team_drive_refresh` | 排队增量更新；`force=true` 重试并重建 |
| `team_drive_job_status` | 查看更新任务与失败情况 |
| `team_drive_cancel` | 请求在安全文件边界取消更新 |

`inventory_complete` 是本次目录盘点完成；`all_present_files_indexed` 是盘点内文件均已解析；`extraction_complete` 是该解析器完成支持内容的提取。它们**都不表示业务资料齐全或视觉内容全部理解**。必须查看 `format_warnings`。当前部分解析失败的文件不会提供成功正文，避免缺失内容被误当完整证据。

Excel 公式与保存值分开返回；保存值可能过期，没有自动重算。Word 页码不稳定，使用段落/表格引用。PPT 图形、PDF 复杂表格、扫描件等存在明确边界。完整限制见 [formats.md](skills/df-mcp/references/formats.md)。

完整汇总应先确定权威来源和业务范围，分页列出并处理全部相关文件，检查遗漏与版本，再使用导出资料和确定性代码计算。导出是服务状态目录中的 JSONL，不是原始二进制文件。`artifact_path` 是运行时返回给本地分析工具的绝对路径，不能将含该路径的完整工具轨迹直接公开发布。

## 更新、限制和性能

运行时默认每 30 秒核对文件元数据，仅解析新增或变化内容。每次证据读取会重新计算原文件 SHA256，故大文件读取仍有顺序 I/O 成本。关闭服务或休眠时不会继续更新，恢复启动后补查。原生操作系统文件事件监听不在本版中。

默认单文件 256 MiB、压缩包总展开体积 512 MiB、100000 个片段、每段 8000 字符、512 列、2000 PDF 页、解析超时 30 秒。超限返回错误，不静默截断。参数可配置，调整前应针对代表性文件验证内存和耗时。

Linux 解析子进程设置地址空间上限；macOS 和 Windows 没有相同的硬内存保证，依靠大小/展开限制和超时。长任务可取消和重启；重启复用已完成文件，单个中断文件重新解析，不承诺从中断行继续。

基准测试：

```sh
.venv/bin/python scripts/benchmark.py --files 1000 --rows 50000
```

Windows 可将命令中的 `.venv/bin/python` 换成 `.venv\Scripts\python.exe`。生成的结果只在 `.local/` 保存。用真实规模验收前，不应承诺任意文件“秒级准确”。

## 开发与发布

TypeScript MCP 适配层在 `src/`；Python 索引与解析在 `python/team_drive/`；Skill 在 `skills/`。业务来源与指标登记示例在 `examples/`，仅供业务层参考，不代表本工具已自动认证资料权威性。

公开发布前执行：

```sh
git add .
npm run check:public
```

检查器扫描 Git 跟踪文本中的凭证模式、私人主目录、邮箱、意外二进制和运行状态文件；它不能替代人工审查。不要提交真实资料、配置、导出、工具完整轨迹、索引或缓存。源码使用 MIT 许可证；依赖保留各自许可证。
