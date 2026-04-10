---
name: Article fetcher integration
description: Status and context for the article-fetcher integration feature (branch osn-article-downloading)
type: project
---

Design and implementation plan are complete and committed on branch `osn-article-downloading`.

- Spec: `.claude/plans/2026-03-22-article-fetcher-integration-design.md`
- Plan: `.claude/plans/2026-03-22-article-fetcher-integration-plan.md`

**Why:** Wire the already-implemented `article-fetcher` service into ChemCrow2 so DOIs from `literature_search` are automatically downloaded, shown as inline cards in chat, and fed into the AI agent's context on each message.

**How to apply:** In the next session, execute using superpowers:subagent-driven-development skill against the plan file above.
