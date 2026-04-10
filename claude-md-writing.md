# Writing CLAUDE.md Files: Best Practices

A reference for writing effective CLAUDE.md files in Claude Code projects.
Treat this file the same way — keep it current, prune it ruthlessly.

---

## What CLAUDE.md Is (and Isn't)

Claude Code starts every session with a blank context window. CLAUDE.md is the
one file that is automatically loaded at the start of every conversation,
giving Claude persistent project context it would otherwise have to rediscover.

**Critical caveat:** Claude Code wraps CLAUDE.md content in a `<system-reminder>`
block that tells Claude the content "may or may not be relevant" and to ignore
it if it doesn't seem applicable. This is intentional — it prevents bad
instructions from derailing unrelated tasks — but it means **irrelevant or
bloated content actively undermines your relevant instructions**. Write only
what applies broadly to almost every task in this project.

---

## File Locations and Hierarchy

Claude Code merges CLAUDE.md files from multiple locations, in order:

| Location | Purpose |
|---|---|
| `~/.claude/CLAUDE.md` | Personal global defaults — applies to all projects |
| `./CLAUDE.md` or `./.claude/CLAUDE.md` | Project root — commit to git, shared with team |
| `CLAUDE.local.md` | Personal project overrides — add to `.gitignore` |
| Subdirectory `CLAUDE.md` files | Scoped rules — loaded on demand when Claude reads files in that directory |

**Subdirectory loading is lazy.** Files above the working directory are loaded
at launch in full. Subdirectory CLAUDE.md files only load when Claude is
actively working with files in that subtree. This is a feature, not a bug —
it keeps irrelevant context out of the window.

**Watch for conflicts.** If a root-level file says "use Prettier" and a
subdirectory file says "use Biome," Claude may pick one arbitrarily. Keep
shared rules at the root and only put genuine overrides in subdirectories.

---

## What Belongs in CLAUDE.md

Think in three categories:

- **WHAT** — Tech stack, project structure, codebase map. Especially important
  in monorepos. Tell Claude what each package/service does and where to find
  things.
- **WHY** — Purpose and function of different parts of the project.
  Architectural decisions, non-obvious constraints.
- **HOW** — How Claude should actually work. Build tools (`bun` not `node`?),
  test commands, how to verify changes, workflow conventions.

**Concrete inclusions:**
- One-liner project description
- Build, test, lint, and deploy commands
- Project-specific gotchas and foot-guns
- What Claude gets wrong without guidance (see Compounding Engineering below)
- Architectural decisions Claude should respect

**Do NOT include:**
- Code style rules a linter enforces — use hooks to run the linter instead
- Things Claude already does correctly without being told
- Documentation that belongs in a skill or referenced file
- Time-sensitive or environment-specific details that will become stale
- Personal preferences (put those in `CLAUDE.local.md`)

---

## Size and Structure

**Target: under 200 lines.** The official docs flag files over 200 lines as
consuming enough context to reduce adherence. Claude Code's built-in system
prompt already consumes ~50 of the ~150–200 instructions a frontier model can
reliably follow. Every instruction in CLAUDE.md competes with that budget.

**The pruning test:** For each line, ask "Would removing this cause Claude to
make a mistake?" If not, cut it or move it to a skill.

**Structure matters.** Use markdown headers and bullets to group related
instructions. Claude scans structure the same way readers do — organized
sections are easier to follow than dense paragraphs.

**Specificity matters.** Write instructions concrete enough to verify:
- ❌ `"Never use --foo-bar flag"` — Claude gets stuck
- ✅ `"Never use --foo-bar; prefer --baz instead"` — gives an alternative

---

## Offloading Content

Don't try to fit everything into CLAUDE.md. Use the right tool:

- **`@imports`** — Reference other files inline:
  ```
  See @README.md for project overview.
  See @docs/git-workflow.md for branching conventions.
  ```
  The referenced file is only loaded when relevant, not on every turn.

- **`.claude/rules/` files** — For instructions that only apply to specific
  file types or subdirectories. Keeps the root CLAUDE.md lean.

- **Skills** — For domain knowledge or workflows that are only sometimes
  relevant. Claude loads them on demand without bloating every conversation.

- **Hooks** — For things that must happen deterministically every time
  (linting after edits, blocking writes to certain directories). Unlike
  CLAUDE.md instructions, hook output arrives without the "may or may not be
  relevant" disclaimer — use hooks for non-negotiable invariants.

---

## Compounding Engineering

The highest-leverage habit: **every time Claude does something wrong and you
correct it, add a rule to CLAUDE.md so it never repeats.**

Boris Cherny (Claude Code's creator) uses this pattern internally with a
`lessons.md` file — after corrections, Claude writes a rule that prevents the
same mistake. On a team, every rule one person adds benefits everyone else's
sessions automatically.

Update CLAUDE.md when:
- Claude makes a mistake you had to correct
- Your tech stack changes
- A code review reveals an undocumented convention
- A pattern violation keeps recurring

---

## Emphasis and Enforcement

For rules that are critical, `IMPORTANT:` or `YOU MUST` increases the odds
Claude pays attention — but use emphasis sparingly. If everything is
`IMPORTANT`, nothing is.

For absolute enforcement, use hooks instead of emphasis. Hook output is
injected without the "may or may not be relevant" framing and survives context
compaction. CLAUDE.md instructions do not reliably survive `/compact`.

---

## Subdirectory CLAUDE.md Files

Worth creating when a subdirectory has genuinely different orientation needs:
- A monorepo package with its own toolchain, conventions, or deployment rules
- A layer with special constraints (`migrations/` — never edit directly)
- A domain with different patterns from the root (e.g., API vs. frontend)

Not worth creating when:
- The content could just be a section in the root file
- You'd be duplicating rules that already exist at the root
- Nobody is actively maintaining it (stale subdirectory files mislead Claude)

**The test:** Would someone new to *that specific subdirectory* need different
orientation than someone working from the project root? If yes, split it.

---

## Getting Started

```
/init
```

This analyzes your codebase and generates a starter CLAUDE.md. Use it as a
starting point, then delete what Claude already does correctly without being
told — generated files tend to be generic and bloated. Deleting is easier than
writing from scratch.

---

## Maintenance Checklist

- [ ] File is under 200 lines
- [ ] Every line passes the pruning test ("would removing this cause a mistake?")
- [ ] No code style rules that a linter already enforces
- [ ] No duplicated content that belongs in a skill or referenced file
- [ ] Checked into git (except `CLAUDE.local.md`)
- [ ] No conflicting instructions across subdirectory files
- [ ] Updated after the last round of corrections

---

## Quick Reference: DO / DON'T

| DO | DON'T |
|---|---|
| Write what Claude gets wrong without guidance | Write what Claude already does correctly |
| Use `@imports` for large reference docs | Embed entire docs inline |
| Use hooks for non-negotiable invariants | Rely on CLAUDE.md for hard enforcement |
| Update after every correction | Set it and forget it |
| Keep shared rules at root, overrides in subdirs | Duplicate the same rules across files |
| Use skills for domain-specific, on-demand context | Dump all knowledge into CLAUDE.md |
| Commit to git for team sharing | Put personal preferences in the shared file |
