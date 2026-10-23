# Team Drive MCP

给 AI 使用的本地团队文件读取工具：**Skill + MCP + SQLite 增量索引**。优先保证来源、版本和读取范围可核查，再优化定位速度。所有附带业务数据均为 **SIMULATED / 完全虚构**。

- [完整中文开发方案](docs/TEAM_AGENT_DEVELOPMENT_PLAN.md)
- [Skill 操作规范](skills/team-drive-read/SKILL.md)
- [验证记录与限制](docs/VALIDATION.md)
- [10 个固定评估任务](tests/evaluation.xml)

## 已实现的范围

- 本地 stdio MCP，9 个结构化工具；不调用模型 API、不访问网络。
- SQLite 文件清单与关键词索引，支持中文短词、项目代号及配置别名。
- TXT、Markdown、CSV、TSV、XLSX、DOCX、PPTX、文字 PDF。
- 启动扫描、运行期间定期增量核对、删除失效、失败记录和强制重试。
- 分页、结构导航、原文定位、读取前 SHA256 版本校验、受控 JSONL 导出。
- 授权根目录边界、符号链接拒绝、压缩文件/XML 限制、超时、明确错误。

**当前运行平台：macOS / Linux，Node.js >=22，Python >=3.9。** 文件安全边界依赖 POSIX API，原生 Windows 会明确拒绝启动；Windows 适配及其验收属于后续开发，不能把本版本描述成已覆盖所有公司电脑。

**当前未实现：** SharePoint 登录与下载、多用户身份权限、OCR、向量检索、原始文件下载工具、模型自我训练、无人值守云端部署。没有真实团队资料，也没有公司 PPT 模板。

## 安装和测试

进入仓库目录后执行：

```sh
npm ci --ignore-scripts
npm run setup
npm test
npm run test:mcp
```

`setup` 在仓库 `.venv` 安装 Python 依赖并编译 TypeScript。无需数据库服务器和模型 API key。测试使用临时目录和虚构资料，不读取你的其他文件夹。

安装 Skill 到个人 Codex 技能目录：

```sh
npm run install:skill
```

安装脚本拒绝覆盖已存在的同名 Skill；后续更新请先比较旧版。Skill 只包含操作规范，**MCP 连接需要另外配置**。

## 配置 MCP

先用随附模拟目录验证。在已安装 Codex CLI 的终端中执行：

```sh
codex mcp add team_drive -- node "$(pwd)/dist/index.js" --config "$(pwd)/examples/config.sample.json"
```

其他支持 stdio 的客户端可参考 [examples/mcp.json](examples/mcp.json)，将路径占位符替换为本机实际路径。启动新会话，使客户端发现 Skill 与工具。

同一个 `state_dir` **只允许一个活跃服务进程**。多窗口/多客户端需要关闭旧连接，或使用各自的配置和状态目录；不要让它们共同打开同一索引库。正常 MCP 客户端会保持会话连接，无需手动先运行 `npm start`。

示例请求：

```text
使用 $team-drive-read 查模拟资料里星河计划 2026-09 的正式预算及可用金额，说明口径并引用单元格。
```

AI 应先检查索引状态，区分正式资料与草稿，读取证据，再用确定性程序计算。搜索结果不能证明业务数据完整。

## 使用自己的获准文件夹

新建本地配置，例如 `.local/config.json`：

```json
{
  "provider": "local",
  "root": "/path/to/approved-source",
  "state_dir": "/path/to/local-private-state",
  "poll_seconds": 30,
  "aliases": { "花费": ["支出"], "达人": ["KOL"] }
}
```

路径也可以相对于配置文件。`state_dir` 必须在源目录之外，不能位于团队共享/云同步目录。它包含派生正文、缓存、数据库和导出，按源资料的敏感程度管理。索引不需要把整库上传云端；AI 选中的片段仍受宿主模型的数据处理规则约束。

将 MCP 的 `--config` 改为新配置后重新连接。一个状态目录绑定一个源目录，不能拿旧状态目录直接切换新资料库。源文件只读；服务只写自己的状态目录。

对于 OneDrive/网络挂载，请先用获准且已完整下载到本机的目录测试。服务会对可识别的在线占位文件标记 `online_only`，不主动下载；不同同步客户端的占位识别仍需实测。

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

Excel 公式与保存值分开返回；保存值可能过期，没有自动重算。Word 页码不稳定，使用段落/表格引用。PPT 图形、PDF 复杂表格、扫描件等存在明确边界。完整限制见 [formats.md](skills/team-drive-read/references/formats.md)。

完整汇总应先确定权威来源和业务范围，分页列出并处理全部相关文件，检查遗漏与版本，再使用导出资料和确定性代码计算。导出是服务状态目录中的 JSONL，不是原始二进制文件。`artifact_path` 是运行时返回给本地分析工具的绝对路径，不能将含该路径的完整工具轨迹直接公开发布。

## 更新、限制和性能

运行时默认每 30 秒核对文件元数据，仅解析新增或变化内容。每次证据读取会重新计算原文件 SHA256，故大文件读取仍有顺序 I/O 成本。关闭服务或休眠时不会继续更新，恢复启动后补查。原生操作系统文件事件监听不在本版中。

默认单文件 256 MiB、压缩包总展开体积 512 MiB、100000 个片段、每段 8000 字符、512 列、2000 PDF 页、解析超时 30 秒。超限返回错误，不静默截断。参数可配置，调整前应针对代表性文件验证内存和耗时。

Linux 解析子进程设置地址空间上限；macOS 没有相同的硬内存保证，依靠大小/展开限制和超时。长任务可取消和重启；重启复用已完成文件，单个中断文件重新解析，不承诺从中断行继续。

基准测试：

```sh
.venv/bin/python scripts/benchmark.py --files 1000 --rows 50000
```

生成的结果只在 `.local/` 保存。用真实规模验收前，不应承诺任意文件“秒级准确”。

## 开发与发布

TypeScript MCP 适配层在 `src/`；Python 索引与解析在 `python/team_drive/`；Skill 在 `skills/`。业务来源与指标登记示例在 `examples/`，仅供业务层参考，不代表本工具已自动认证资料权威性。

公开发布前执行：

```sh
git add .
npm run check:public
```

检查器扫描 Git 跟踪文本中的凭证模式、私人主目录、邮箱、意外二进制和运行状态文件；它不能替代人工审查。不要提交真实资料、配置、导出、工具完整轨迹、索引或缓存。源码使用 MIT 许可证；依赖保留各自许可证。
