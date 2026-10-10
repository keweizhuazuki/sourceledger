[English](README.md)

# SourceLedger

**来源变了，知道哪些笔记需要重新检查。**

面向 Markdown 手册、操作指南、研究笔记和智能体知识目录的本地复核队列。声明笔记依赖的本地文件或章节，查看来源差异，检查笔记后再明确确认基线。不会自动改写笔记、调用模型、请求外部网址，也不会判断内容是否真实。

![CI 中 Chromium 实际渲染的桌面报告](docs/images/report-desktop.png)

[手机截图](docs/images/report-mobile.png) · [实际 HTML 示例](docs/example-report.html)

## 运行完整示例

需要 Python 3.10+ 和 Git；没有运行时依赖，无需服务账号。

Linux / macOS：

```sh
git clone https://github.com/keweizhuazuki/sourceledger.git
cd sourceledger
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python examples/demo.py
```

Windows PowerShell（无需激活虚拟环境）：

```powershell
git clone https://github.com/keweizhuazuki/sourceledger.git
cd sourceledger
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe examples\demo.py
```

示例复制手册到临时目录，确认初始来源，将访问期限从 30 天改为 14 天，再在当前目录生成 `demo-report.html`。用浏览器打开即可。再次运行不会覆盖已有报告，请先移动报告。仓库中的示例不会被改动。也可直接在源码目录运行 `python -m sourceledger`，无需安装。

实际示例的关键输出：

```text
0 new, 1 changed, 1 current, 0 error

[CHANGED] onboarding.md ← policy.md → Access [1]
--- accepted
+++ current
@@ -1,4 +1,4 @@
 ## Access
 
-Temporary access lasts 30 days. A manager must approve it.
+Temporary access lasts 14 days. A manager must approve it.
```

Windows 未激活虚拟环境时，在源码目录中将后续命令的 `sourceledger` 替换为 `.venv\Scripts\sourceledger.exe`；从其他目录运行时请使用该程序的完整路径。也支持通过 `python -m pip install .`（Windows 未激活时用 `.venv\Scripts\python.exe -m pip install .`）普通安装（非可编辑安装），安装后的 CLI 可在源码目录外运行。Git 用于克隆及 `suggest-renames`，普通本地复核无需 Git。

## 接入已有知识库

1. 运行 `sourceledger --root /path/to/notes init`。
2. 编辑生成的 `sourceledger.json`，填写真实依赖。所有系统都使用相对路径和正斜杠。
3. 用 `sourceledger --root /path/to/notes headings sources/policy.md` 查看准确标题和重复次数。
4. 运行 `sourceledger --root /path/to/notes check`。首次追踪也需要复核。
5. 检查来源差异与笔记，必要时自行修改笔记；改完再次运行 `check` 获取最新令牌。
6. 用 `sourceledger --root /path/to/notes accept --token TOKEN` 确认这次复核。

```json
{
  "version": 1,
  "dependencies": [
    {"note": "notes/onboarding.md", "source": "sources/policy.md", "heading": "Access", "occurrence": 1},
    {"note": "notes/onboarding.md", "source": "sources/support.md"}
  ]
}
```

不填 `heading` 即追踪整个 UTF-8 文件。章节包含子章节，到下一个同级或更高级标题为止；无关章节修改不会触发复核。仅支持大小写敏感、精确匹配的 ATX 标题（`#` 到 `######`）。重复标题用从 1 开始的 `occurrence` 区分，顺序以文档为准。忽略围栏代码块内的标题。不支持 Setext、HTML 标题或渲染器的锚点规则。

### 单篇复核与导出

```sh
sourceledger --root ./handbook check --note notes/onboarding.md
sourceledger --root ./handbook accept --note notes/onboarding.md --token TOKEN
sourceledger --root ./handbook check --format html --output review.html
sourceledger --root ./handbook check --format json --output review.json
```

检查和确认使用相同的 `--note`。所选来源、笔记、依赖标识或已确认基线变化后，旧令牌失效。令牌用于防止确认过时报告，不是密码或签名。不会覆盖已有输出文件。命令行输出与保存的报告统一使用 UTF-8。

无效的知识库根目录（目录不存在、普通文件、不可访问路径或符号链接循环）返回操作错误，不会误报为待复核。

退出码：`0` 所选来源无变化或操作成功；`1` 新增或变化需要复核；`2` 配置错误、来源/笔记/章节缺失、读取失败或操作失败。来源被删除或重命名属于错误，不会自动确认删除；请明确修正路径并重新复核。

## 从已有 Markdown 链接发现候选依赖

```sh
sourceledger --root ./handbook discover notes/onboarding.md
sourceledger --root ./handbook discover notes/onboarding.md notes/support.md --format json --output proposal.json
python -m sourceledger --root examples discover discovery/note.md
```

发现命令仅读取指定笔记及链接指向的本地 UTF-8 文件，不创建或打开基线数据库，不修改清单，不确认来源，也不请求网络。报告提供去重后的候选、可复制到清单的 `dependency` 对象、原始行号/链接以及来源和笔记哈希，并说明跳过原因。见[真实混合案例输出](docs/discovery-example.txt)。

先复核报告，再把选中的 `dependency` 对象复制到 `sourceledger.json` 的 `dependencies` 数组（需要时先运行 `init`）。随后运行 `check`，检查实际来源快照，再用新令牌明确 `accept`。候选报告带独立的 `kind`，不能直接作为清单使用；命令拒绝写入 `sourceledger.json` 或覆盖已有报告。没有自动应用步骤，因为链接可能只是导航，不一定是笔记结论的依据。

支持的有限语法：

- 普通单行行内链接，例如 `[policy](../sources/policy.md#access)`；尖括号内带空格的路径；百分号编码的 UTF-8 路径/片段；目标中配对或转义的括号；可选的单引号/双引号标题。
- 路径相对笔记解析，必须在所选根目录内并指向可读的 UTF-8 文件。相同依赖去重，但保留每个来源行号。
- 片段采用保守的纯文本标题规则：目标的所有 ATX 标题仅含 Unicode 单词字符、ASCII 空格、连字符或下划线；转小写后每个空格替换为连字符，冲突按文档顺序追加 `-1`、`-2` 等并跳过已用标识。不保证与 GitHub、Obsidian 或其他渲染器完全等价。HTML/注释、列表/引用容器或 Setext 语法、非纯文本标题和未知片段需要用 `headings` 检查并手动配置。
- 忽略围栏/缩进代码、行内代码及 HTML 注释。原始/行内 HTML、引用式或 Wiki 链接所在行、多行链接/标题、图片、查询字符串、外部协议和同页导航会被跳过或标为不支持。这不是完整 CommonMark 解析器；复杂嵌套标签和未闭合分隔符需人工检查，保守处理可能跳过整行或整块。

成功生成报告退出 `0`，即使有跳过项；指定笔记无效或输出失败退出 `2`。候选不保证完整，也不证明事实依赖关系。发现后来源若变化，仍由正常的 `check`/`accept` 流程重新检查。

## 为暂存的 Git 重命名提供候选

```sh
sourceledger --root ./handbook suggest-renames
sourceledger --root ./handbook suggest-renames --format json
python examples/rename_demo.py
```

可复现的问题：执行 `git mv policy.md access-policy.md` 后，清单仍引用旧来源，`check` 会正确报错。新命令仅用现有本地 Git 元数据帮助找到可能的替代路径。[实际临时示例输出](docs/rename-example.txt) 重现错误，并验证建议过程没有改变清单、Git 索引或基线数据库的字节。

对每个缺失的笔记/来源路径，比对相对于 HEAD 的暂存普通文件删除与新增记录，只列出 **Git blob ID 完全相同**、位于所选根目录内且可读的 UTF-8 候选。多个新增或删除文件共享同一 blob 时明确标记歧义；即使只有一个候选，也不等于证明发生了重命名。当前候选必须仍包含所需来源章节。JSON 同时给出当前规范化文本哈希，但完全一致的证据仅针对暂存内容，工作区可能另有未暂存修改。

请检查路径与当前内容，自行修改清单，再运行 `check` 并明确确认新依赖。不会迁移旧基线或历史，也不会为仍存在的路径建议替换。

范围限制：不做相似度猜测，不处理未暂存/未跟踪移动、已提交历史重命名、二进制、符号链接/子模块条目，不联网或修改仓库。需安装 Git、存在 HEAD、根目录位于本地工作树内，路径须为 UTF-8。没有精确暂存匹配时保持未解决；拒绝越界符号链接及不可读、缺少所需章节的候选。不支持根目录名称含换行，也不为经过符号链接别名的缺失路径推断 Git 替代路径。

对子进程临时禁用外部 diff、文本转换、hooks、文件系统监视 hook、延迟抓取、传输协议、继承的 Git 覆盖配置和可选写操作，不更改用户或仓库设置。每条命令限时 10 秒，拒绝超过 8 MiB 的元数据输出。这不是针对恶意 Git 安装或并发恶意工作区修改的沙箱。退出 `0` 表示已生成报告（可包含未解决项），`2` 表示配置或 Git 检查失败。

## 查看确认历史

```sh
sourceledger --root ./handbook history
sourceledger --root ./handbook history --note notes/onboarding.md --limit 5
sourceledger --root ./handbook history --before 12 --limit 5
sourceledger --root ./handbook history --format json
```

每次成功的 `accept` 记录一个批次，包含 UTC 时间、复核令牌、确认范围，以及各依赖的修订号、确认来源原文、上一版原文和笔记哈希。文本输出显示来源标识与 SHA-256 指纹，JSON 包含保存的原文。历史查询不重新读取来源，也不需要有效清单，因此文件重命名、删除或依赖移除后仍可查询。

按批次 ID 从新到旧排列。`--limit` 支持 1–100 个批次，默认 20；`--before` 分页不受新确认记录插入影响。`--note` 同时过滤批次和其中显示的依赖；按下一页提示查询时保持该过滤条件。再次确认未变化的来源，也会记录一次明确复核并增加修订号。

旧数据库自动迁移，原基线与修订号保持不变。过去没有记录的确认时间不会凭空生成，历史从下一次成功确认开始。确认失败或令牌过时不会留下批次或部分历史。时间来自本机 UTC 时钟；这是本地复核依据，不是带签名、防篡改的审计日志。重复来源快照会使数据库持续增长，目前没有自动保留期限或清理功能。请自行备份，并将历史 JSON 导出视为可能包含敏感内容的文件。

[实际示例输出](docs/demo-output.txt) 包含首次确认记录；其中的时间与令牌仅作展示，不应直接复用。

## 用于离线 CI 的便携基线

完成正常人工复核和 `accept` 后，导出已确认状态：

```sh
sourceledger --root ./handbook export-baseline --output reviewed-baseline.json
sourceledger --root ./fresh-checkout check --baseline reviewed-baseline.json
sourceledger --root ./fresh-checkout check --baseline reviewed-baseline.json --format html --output ci-review.html
python examples/baseline_demo.py
```

Windows 未激活虚拟环境时，在源码目录中使用 `.venv\Scripts\sourceledger.exe` 和 `.venv\Scripts\python.exe`。快照与报告路径相对于当前工作目录；笔记和来源路径仍相对于 `--root`。

导出仅包含当前清单中已确认的来源文本和笔记哈希。每个跟踪依赖都必须已有基线；未确认的编辑不会被自动写入快照。当前笔记或来源缺失不影响导出其已确认记录。拒绝覆盖已有输出文件，只读访问现有数据库，不创建或迁移数据库。支持 SourceLedger 默认的回滚日志数据库；对于被外部转换为 WAL 模式的数据库会明确拒绝，以免创建旁文件或导出过时数据。不会执行检查点操作或切换日志模式；导出时请停止外部数据库维护。

`check --baseline` 读取快照及当前本地文件，不打开或创建 SQLite。支持 `--note`、文本/JSON/HTML 和原有退出码：0 表示当前一致，1 表示新增或变化依赖，2 表示无效输入或缺失文件/章节。清单新增依赖需要复核；快照中已从清单移除的依赖单独列出，本身不改变退出码。笔记编辑仍像普通检查一样提示人工复核。快照报告不提供确认令牌；执行 `accept` 前需重新运行普通本地 `check`。

严格的版本 1 JSON 包含依赖标识、已确认来源文本、SHA-256 内容哈希及已确认笔记哈希。限制为快照 8 MiB、单条已确认文本 2 MiB、10,000 条依赖。拒绝未知版本/字段、重复 JSON 字段/依赖、无效路径/类型/哈希及错误 UTF-8。内容哈希仅验证内部一致性，**不证明来源可信或真实性**。CI 必须独立于被检查的改动取得可信且已复核的快照；若同时接受该改动替换的基线，可能掩盖来源变化。工具不负责执行分支策略。

快照包含来源摘录和文件路径。敏感快照应保持私密，不要自动提交或发布。[真实合成示例输出](docs/baseline-example.txt) 与 [HTML 报告](docs/baseline-report.html) 不含用户数据。不支持迁移历史确认或合并基线；下文介绍需复核的空数据库导入。不虚构确认历史。

## 明确复核后导入基线

导入仅用于以可信快照初始化**空的**本地数据库。CI 仍可直接使用 `check --baseline`，无需导入。

```sh
sourceledger --root ./fresh-checkout import-baseline reviewed-baseline.json
sourceledger --root ./fresh-checkout import-baseline reviewed-baseline.json --token IMPORT_TOKEN
sourceledger --root ./fresh-checkout history
sourceledger --root ./fresh-checkout check
python examples/import_demo.py
```

第一条命令只预览，不写入：展示确切的已确认来源文本、依赖标识、哈希和导入令牌。请检查这些内容，并独立核实快照来源可信。支持 `--format json`。只有明确提供令牌的命令才会写入。令牌绑定快照及匹配的清单；快照/清单变化或目标非空都会拒绝导入。导入令牌用于防止过期预览，不是身份认证，也不是本地确认令牌。

导入要求快照依赖标识与当前清单完全一致，目标没有任何基线、确认历史或既往导入记录。不会合并或覆盖已使用的数据库，即使只剩历史记录也不允许。预览不创建存储、不迁移已有结构；只读检查会拒绝外部配置的 WAL 数据库，避免创建旁文件。快照比较仍完全不访问数据库。

实际导入在 SQLite 写事务内重新检查快照、清单、令牌及空状态。基线与导入来源记录一起提交或回滚，并发导入不能同时成功。无效令牌在创建存储前拒绝。有效预览之后若发生 I/O 或事务错误，可能留下空的已初始化/迁移数据库，但不会留下部分导入行。导入期间请停止外部数据库维护及并发文件系统修改。

导入基线从本地修订号 1 开始。`history` 将导入时间、快照摘要和确切导入条目**单独列出，与本地确认批次区分**，不虚构原始确认时间。后续确认不会覆盖导入记录；历史分页的每页都单独显示导入来源，使用相同笔记筛选条件。已有数据库以事务方式迁移至结构版本 2，保留已确认内容和历史。

导入代表信任保存的基线，不代表批准当前文件。笔记/来源可能已变化或缺失；后续普通 `check` 会报告差异或错误，真正执行 `accept` 才记录新的本地确认。不会改写文件。见[真实合成导入示例](docs/import-example.txt)。快照哈希仍只是完整性检查，不证明来源；不上传快照、不抓取远程内容，也不自动确认。

## 数据与安全边界

- 已确认的来源原文保存在 `.sourceledger/state.sqlite3`。来源敏感时，数据库也敏感；不要提交到公开仓库，并自行备份以保留复核记录。
- `check` 会创建或打开本地数据库，但不会修改已确认基线。确认使用 SQLite 单次事务；任何一个所选依赖出错，整批不确认。
- 只读取普通 UTF-8 文件，每个最多 2 MiB；拒绝管道、设备文件及符号链接环。拒绝绝对路径、目录外路径和解析后越界的符号链接。不要在其他进程恶意修改的目录运行；这不是文件系统沙箱。
- 读取发生在检查或确认时，不提供整个文件系统的原子快照。确认期间请暂停并发编辑；SQLite 会串行处理并发确认。
- 报告可能包含完整来源片段，分享前请检查。HTML 已转义，无脚本，不加载外部资源。
- 不抓取网络来源，无定时后台服务、通知、云同步、遥测或事实核验，不自动修改笔记。移除清单中的依赖后不再检查，旧基线原文仍保留在数据库中。

## 定位与验证

链接检查器检查目标是否存在；网页监测工具检查页面是否变化；SourceLedger 将来源变化关联到依赖它的本地笔记，并记录明确复核。见[调研与替代方案](docs/research.md)。独立实现，不宣称全球首创，也不宣称兼容所有 Markdown 渲染器。

```sh
python -m unittest discover -s tests -v
python -m compileall -q sourceledger tests
```

验证日期为 2026-10-11（Asia/Shanghai）：[CI 运行 38076905944](https://github.com/keweizhuazuki/sourceledger/actions/runs/38076905944) 的 Linux/macOS/Windows × Python 3.10/3.13 共六个任务全部通过，包含 105 项测试、安装、编译检查和实际示例（包括便携基线场景）。Chromium 桌面/手机布局与无网络请求断言也通过。上面的截图来自 CI 对仓库内真实示例报告的渲染。禁止创建符号链接的平台会跳过相关测试，不支持命名管道的系统也会跳过对应测试；这些验证不代表支持所有文件系统或 Markdown 方言。

## 已完成与下一步

已完成：整文件/章节依赖、令牌绑定的明确确认、单篇复核、来源缺失错误、事务基线、文本/JSON/HTML 报告、可运行的一次性示例、带原子迁移、单篇筛选与分页的确认历史、只读且需复核的链接发现与路径/片段诊断、只读精确暂存 Git 替代路径建议、已确认基线导出与无需数据库的 CI 快照检查、需明确复核的空数据库导入及独立来源记录、125 项回归测试、受控的无效根目录错误、Windows UTF-8 输出与数据库清理验证、桌面/手机浏览器检查。

已完成批次见[变更记录](CHANGELOG.md)。

下一步：更多 Markdown 锚点规则；根据实际使用改进导入/历史保留体验。不承诺日期。反馈请说明反复遇到的实际任务，并提供不含敏感信息的最小示例。

本仓库尚未选择或授予许可证。
