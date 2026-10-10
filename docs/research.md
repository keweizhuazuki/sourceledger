# Product selection evidence

Research performed 2026-10-10 UTC / 2026-10-11 Asia/Shanghai. GitHub Trending HTML was fetched live, separately for [daily](https://github.com/trending?since=daily) and [weekly](https://github.com/trending?since=weekly). Trending changes continuously; these are observations, not rankings promised for another time.

- Daily included mksglu/context-mode, mattpocock/skills, and anthropics/knowledge-work-plugins.
- Weekly included thedotmack/claude-mem, cursor/plugins, and ranxianglei/billion-context.
- [context-mode's original README](https://github.com/mksglu/context-mode) describes indexing/retrieval and session continuity. [Issue 895](https://github.com/mksglu/context-mode/issues/895) reports stale cross-session captures ranking above fresh content. This supports the relevance of provenance and freshness, but does not prove demand for SourceLedger specifically.
- [changedetection.io issue 3818](https://github.com/dgtlmoon/changedetection.io/issues/3818) describes difficulty using different diff outputs; [issue 962](https://github.com/dgtlmoon/changedetection.io/issues/962) describes notifications with blank differences. These are original user reports, not claims that those bugs remain unresolved. They informed explicit inspectable baselines and readable diffs.

## Alternatives and scope

[lychee](https://github.com/lycheeverse/lychee) checks broken links across Markdown and other formats. [changedetection.io](https://github.com/dgtlmoon/changedetection.io) monitors website changes and notifications. Git diff already shows file changes. Agent memory projects preserve or retrieve context. All can be the better tool for their own job.

SourceLedger's hypothesis is narrower: knowledge-base owners need a review queue joining local source changes to dependent notes, scoped to meaningful sections, with explicit human acceptance. The initial implementation avoids external fetching, embedding services, probabilistic extraction, and background agents. It does not claim that existing projects lack all similar features, or that freshness establishes truth.

Next validation should use maintainers' real repeated workflows and non-sensitive fixtures. Repository popularity is inspiration, not user validation. No surveys, outreach, fabricated usage metrics, or copied implementation were used.
