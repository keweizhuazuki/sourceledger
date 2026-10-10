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

退出码：`0` 所选来源无变化或操作成功；`1` 新增或变化需要复核；`2` 配置错误、来源/笔记/章节缺失、读取失败或操作失败。来源被删除或重命名属于错误，不会自动确认删除；请明确修正路径并重新复核。

## 数据与安全边界

- 已确认的来源原文保存在 `.sourceledger/state.sqlite3`。来源敏感时，数据库也敏感；不要提交到公开仓库，并自行备份以保留复核记录。
- `check` 会创建或打开本地数据库，但不会修改已确认基线。确认使用 SQLite 单次事务；任何一个所选依赖出错，整批不确认。
- 每个 UTF-8 文件最多 2 MiB。拒绝绝对路径、目录外路径和解析后越界的符号链接。不要在其他进程恶意修改的目录运行；这不是文件系统沙箱。
- 读取发生在检查或确认时，不提供整个文件系统的原子快照。确认期间请暂停并发编辑；SQLite 会串行处理并发确认。
- 报告可能包含完整来源片段，分享前请检查。HTML 已转义，无脚本，不加载外部资源。
- 不抓取网络来源，无定时后台服务、通知、云同步、遥测或事实核验，不自动修改笔记。移除清单中的依赖后不再检查，旧基线原文仍保留在数据库中。

## 定位与验证

链接检查器检查目标是否存在；网页监测工具检查页面是否变化；SourceLedger 将来源变化关联到依赖它的本地笔记，并记录明确复核。见[调研与替代方案](docs/research.md)。独立实现，不宣称全球首创，也不宣称兼容所有 Markdown 渲染器。

```sh
python -m unittest discover -s tests -v
python -m compileall -q sourceledger tests
```

初始本地测试在 Linux 运行。CI 配置覆盖 Linux、macOS、Windows 及 Python 3.10/3.13；配置存在不代表已成功执行。无法创建符号链接的平台会跳过相关测试。HTML 来自真实示例数据，浏览器布局验证与单元测试分别记录。

## 已完成与下一步

已完成：整文件/章节依赖、令牌绑定的明确确认、单篇复核、来源缺失错误、事务基线、文本/JSON/HTML 报告、可运行的一次性示例、回归测试。

下一步：本地 Markdown 链接发现并人工选择追踪、更丰富的确认历史、更多 Markdown 锚点规则、CI 基线导入导出、可选的 Git 重命名建议。不承诺日期。反馈请说明反复遇到的实际任务，并提供不含敏感信息的最小示例。

本仓库尚未选择或授予许可证。
