# AGENTS.md

Project instructions for Cursor, Muse, OpenCode, Codex, Antigravity, and any other harness that loads `AGENTS.md`.

Source methodology: [obra/superpowers](https://github.com/obra/superpowers).

---

<EXTREMELY_IMPORTANT>
You have Superpowers.

**Below is the full content of your `using-superpowers` skill — your introduction to using skills. For all other skills, read and follow the matching `SKILL.md` under `.agents/skills/`.**

If you were dispatched as a subagent to execute a specific task, ignore the bootstrap below and do only the assigned task.

If you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke that skill before any response or action — including clarifying questions, exploring the codebase, or checking files. This is not negotiable.

**Before entering plan mode:** if you have not already brainstormed, invoke `brainstorming` first.

Announce `Using [skill] to [purpose]` and follow the skill exactly. If it has a checklist, create a todo per item.

### Skill priority

Process skills first (they set the approach), then implementation skills.

- "Let's build X" → `brainstorming`, then implementation skills
- "Fix this bug" → `systematic-debugging`, then domain skills

### Red flags (STOP — you are rationalizing)

| Thought | Reality |
|---------|---------|
| "This is just a simple question" | Questions are tasks. Check for skills. |
| "I need more context first" | Skill check comes BEFORE clarifying questions. |
| "Let me explore the codebase first" | Skills tell you HOW to explore. Check first. |
| "I can check git/files quickly" | Files lack conversation context. Check for skills. |
| "This doesn't need a formal skill" | If a skill exists, use it. |
| "I remember this skill" | Skills evolve. Read the current `SKILL.md`. |
| "The skill is overkill" | Simple things become complex. Use it. |
| "I'll just do this one thing first" | Check BEFORE doing anything. |

### How to load a skill

1. Prefer the harness native skill tool when available.
2. Otherwise read `.agents/skills/<skill-name>/SKILL.md` and follow it exactly.
3. Platform tool mappings (when needed) live under `.agents/skills/using-superpowers/references/`.

### Installed Superpowers skills

| Skill | Use when |
|-------|----------|
| `using-superpowers` | Starting any conversation (this bootstrap) |
| `brainstorming` | Any creative/new work before coding |
| `writing-plans` | Spec/requirements exist; before touching code |
| `executing-plans` | Running a plan inline in this session |
| `subagent-driven-development` | Executing a multi-task plan with subagents |
| `dispatching-parallel-agents` | 2+ independent parallel tasks |
| `test-driven-development` | Implementing features/fixes (red/green) |
| `systematic-debugging` | Any bug, test failure, or unexpected behavior |
| `verification-before-completion` | Before claiming done / opening PRs |
| `requesting-code-review` | After major work, before merge |
| `receiving-code-review` | When acting on review feedback |
| `using-git-worktrees` | Isolated feature work / plan execution |
| `finishing-a-development-branch` | Implementation complete; integrate next |
| `writing-skills` | Creating or editing skills |
| `diagnosing-superpowers` | Superpowers session went wrong |

User instructions in this file and direct human requests take precedence over skills. Only skip skill workflows when the human partner explicitly says to.
</EXTREMELY_IMPORTANT>

---

## Project conventions

- Design and security references live under `context/`. `context/phases/` holds local implementation notes (gitignored); agents should create/update files there when features change.
- Work on one git branch per phase, named `phase-N-<slug>` (for example `phase-0-scaffold`). Never commit phase work directly to `main`.
- Merge a phase branch into `main` only after the human partner explicitly approves that phase. Approval of one phase is not approval of the next.
- Before starting a phase or feature, create `context/phases/<date>-phase-N-<slug>.md` describing its scope, the plan/spec it follows, and how it will be verified.
- Before merging that phase, finish the same file: what was implemented and which files changed, how it was reviewed (reviewer, commit range, inputs, findings), and the outcomes (test/lint results, manual checks, findings fixed and deferred). Do not merge until this section exists.
- Keep these paths in the project root `.gitignore` (do not commit them): `.agents/skills/`, `.cursor/`, `.opencode/`, `context/phases/`, `docs/`.
- Never touch or view `.env` unless explicitly asked. Only make changes to `.env.example`.
- Never add any agent (including Cursor Agent / cursoragent, Codex, Muse, OpenCode, or similar) as a repository contributor, co-author, or author — not in git commits (`Co-authored-by`, committer identity), `CONTRIBUTORS`, README credits, or GitHub collaborator settings.
- Execution must be sub-agent driven: dispatch a fresh subagent per implementation task plus a fresh reviewer per task, never implement multi-task plans inline in a single session.
- Prefer pointed, concise communication. Do not invent secrets; request them through the harness secret mechanism when available.

## Skill locations

- Canonical project skills: `.agents/skills/<name>/SKILL.md`
- Lockfile: `skills-lock.json` (from `npx skills`)

Update skills later with:

```bash
npx skills update -p -y
```

## Harness-specific setup (native plugins)

Skills in `.agents/skills/` work across AGENTS.md-aware harnesses. For full Superpowers behavior (session-start bootstrap hooks), also install the native plugin per harness:

### Cursor

In Agent chat:

```text
/add-plugin superpowers
```

Or search the plugin marketplace for **superpowers**.

### Muse

```bash
git clone https://github.com/obra/superpowers.git /tmp/superpowers
muse plugins install /tmp/superpowers --scope project
muse plugins approve superpowers
```

Restart Muse sessions after install so `SessionStart` hooks apply.

### OpenCode

Project config (`opencode.json`) should include:

```json
{
  "plugins": ["superpowers@git+https://github.com/obra/superpowers.git"]
}
```

Restart OpenCode. Verify with: `Tell me about your superpowers`.

### Codex

App: Plugins → Coding → **Superpowers** → install.

CLI:

```text
/plugins
```

Search `superpowers` → Install Plugin.

For subagent-driven skills, enable multi-agent in `~/.codex/config.toml`:

```toml
[features]
multi_agent = true
```

### Antigravity

```bash
agy plugin install https://github.com/obra/superpowers
```

Re-run the same command to update.

## Acceptance check

In a fresh session, send:

> Let's make a react todo list

A working setup should trigger `brainstorming` (clarifying questions / design) before any implementation code.
