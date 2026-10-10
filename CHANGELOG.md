# Completed changes / 已完成变更

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

Local Markdown-link discovery with review before tracking; more Markdown anchor dialects; CI baseline import/export; optional Git rename suggestions. History retention/export ergonomics can follow real usage feedback. No release dates or external-service dependency promised.

优先推进本地链接发现与人工选择追踪，再考虑更多锚点规则、CI 基线导入导出及 Git 重命名建议。历史保留与导出体验根据真实使用反馈改进，不承诺日期或外部服务依赖。
