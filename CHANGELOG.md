# Completed changes / 已完成变更

## Reviewed baseline import / 需复核的基线导入 — 2026-10-11 Asia/Shanghai

- Added no-write `import-baseline` previews with exact accepted contents, manifest-matched scope and an explicit import token.
- Token-bound import initializes empty ledgers only. Snapshot, manifest and emptiness are rechecked under the write lock; baselines and provenance commit atomically. Existing data/history is never overwritten.
- Schema 2 preserves separate import provenance and existing local acceptance history. Imported timestamps are never presented as original acceptance times; current edits still require normal review.
- Added migration, rollback, concurrency, stale-preview, no-write and provenance-filter tests plus a disposable synthetic demo; synchronized both README languages and actual output.

新增只读预览与令牌绑定的空数据库导入；事务内重新验证快照、清单及空状态，禁止覆盖。结构版本 2 单独保存准确导入记录并保留原确认历史；补充迁移、回滚、并发、过期预览及筛选测试和真实合成示例。

## Portable accepted baselines / 便携已确认基线 — 2026-10-11 Asia/Shanghai

- Added deterministic `export-baseline` for complete accepted manifest coverage, with exclusive new-file output and no promotion of unaccepted edits.
- Added `check --baseline` for offline CI: no SQLite access, no acceptance token, existing report formats/exit codes, explicit new and removed dependency reporting.
- Strict versioned JSON, duplicate/type/hash/path validation, size limits, legacy read-only export, and explicit WAL rejection prevent ambiguous or silently mutated snapshots.
- [Verified CI](https://github.com/keweizhuazuki/sourceledger/actions/runs/38076905944): six OS/Python jobs and Chromium passed. Added synthetic CLI/HTML examples, browser checks, and 17 snapshot tests (105 total); synchronized English/Chinese safety and CI-trust documentation.
- Import and provenance migration remain deferred. Exported content hashes are not proof of authenticity.

新增已确认基线导出和离线 CI 快照检查；不自动确认编辑，不访问检查端数据库，不生成确认令牌。提供严格格式校验、大小限制、WAL 模式拒绝、真实合成示例及测试。导入和来源记录迁移留待后续，哈希不代表可信来源。

## CLI root errors and installation / CLI 根目录错误与安装 — 2026-10-11 Asia/Shanghai

- Reproduced `--root` symlink loops raising a traceback with exit 1; invalid roots now return the documented operation-error exit 2 without opening baseline storage.
- Added real-path and injected exception regressions for Python version differences; 88 tests pass locally and across all six OS/Python jobs in [CI run 38076246528](https://github.com/keweizhuazuki/sourceledger/actions/runs/38076246528), alongside both demos and Chromium checks.
- Verified a clean non-editable wheel installation on Linux Python 3.12, both entry points outside the checkout, and clarified Windows commands without environment activation. Cross-platform installation remains covered by existing editable-install CI.

修复根目录符号链接循环误返回待复核状态的问题；补充路径与异常回归测试，以及未激活虚拟环境的 Windows 调用方式。验证 Linux Python 3.12 全新普通安装和源码目录外调用；跨平台安装继续由现有可编辑安装 CI 覆盖。

## Staged Git rename suggestions / 暂存 Git 重命名候选 — 2026-10-11 Asia/Shanghai

- Reproduced missing-source failure after `git mv`; added read-only `suggest-renames` for missing manifest note/source paths.
- Exact staged deletion/addition blob matches only; duplicate blobs remain explicitly ambiguous, and unsupported/edited/untracked/committed moves remain unresolved.
- Added process-local Git safety controls, metadata parsing, no-state-change and hook-suppression tests, plus a real disposable Git demo.
- No manifest rewrite, baseline/history migration, Git mutation or network operation.
- [Verified CI](https://github.com/keweizhuazuki/sourceledger/actions/runs/38069408862): 86 tests across six OS/Python combinations, both real demos and Chromium checks. Windows path normalization differences are covered.

重现 Git 移动后旧来源缺失的问题，新增精确暂存 blob 候选报告；明确保留歧义与不支持情况。加入只读/安全边界测试及真实临时示例，不修改清单、基线、历史或 Git，不联网。

## Reviewed link discovery / 需复核的链接发现 — 2026-10-11 Asia/Shanghai

- Added read-only `discover` for explicit Markdown notes: inline local links, relative/percent-encoded paths, conservative plain-ATX fragments, deduplication and line references.
- Separate text/JSON proposals cannot silently become the active manifest. Users explicitly select and copy dependencies, then use the existing check/accept workflow.
- No database access, baseline mutation or network requests. Unsupported syntax, escaped-root paths and unresolved sources/fragments are visible in the report.
- Added a runnable mixed-case fixture, synchronized documentation, and regressions for the review boundary and parsing/path cases.
- [Verified CI](https://github.com/keweizhuazuki/sourceledger/actions/runs/38068508378): 65 tests across six OS/Python combinations plus Chromium checks; OS-specific tests skip where the relevant facility is unavailable.
- Hardened reads against pipes/devices and symlink loops; preserved symlinked notes’ logical relative-link base and literal filename entities; conservatively skipped unsupported markup.

新增只读候选发现、路径/片段解析、去重与行号；候选报告不能直接作为清单使用，需人工选择后走原有复核确认流程。不访问数据库或网络，并提供跳过原因、真实示例和回归测试。

## Acceptance history / 确认历史 — 2026-10-11 Asia/Shanghai

- Added `history` with exact-note filtering, bounded stable pagination, text and JSON output.
- Successful acceptances atomically preserve UTC timestamps, reviewed tokens, scope, revisions, source snapshots, and note hashes alongside baseline updates.
- Existing baseline-only databases migrate in place; missing historical times are never fabricated.
- Failed acceptance or failed history insertion rolls back the complete batch. History remains accessible after notes, sources, or the manifest are removed.
- Added migration, rollback, snapshot, filtering, pagination, concurrency and CLI regressions; synchronized both READMEs and the runnable demo.
- [Verified CI](https://github.com/keweizhuazuki/sourceledger/actions/runs/38067579257): 37 tests across six OS/Python combinations, plus the Chromium report checks.

新增确认历史命令、单篇过滤、分页及文本/JSON 输出；确认记录与基线在同一事务保存。旧数据库保留基线并迁移，不虚构历史时间；失败时整批回滚，删除原文件后仍能查询历史。同步中英文说明、示例和回归测试。

## Initial usable product / 首个可用版本 — 2026-10-11 Asia/Shanghai

- Local whole-file/ATX-section dependency review, explicit token-bound acceptance, SQLite baselines, and text/JSON/static-HTML reports.
- Fixed Windows database cleanup and UTF-8 output, stale note-hash acceptance, empty headings, and missing-final-newline diff rendering.
- Verified six OS/Python CI combinations and Chromium desktop/mobile reports, with genuine screenshots.

完成本地依赖复核、明确确认、数据库基线与报告；修复 Windows 兼容性和复核一致性问题，并通过跨平台及浏览器验证。

## Next / 下一步

More Markdown anchor dialects; import/history retention ergonomics based on real usage. History retention/export ergonomics can follow real usage feedback. No release dates or external-service dependency promised.

下一步考虑更多锚点规则，并根据实际使用改进导入/历史保留体验。历史保留与导出体验根据真实使用反馈改进，不承诺日期或外部服务依赖。
