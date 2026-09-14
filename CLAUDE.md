# EvidenceFlow — project instructions

## GitHub commit rules

- Never add any Claude or AI attribution to anything that reaches GitHub. No
  `Co-Authored-By: Claude`, no `Claude-Session`, no "Generated with Claude Code",
  no attribution footer, in commit messages, merge commits, tags, pull request
  titles or bodies, issue comments, review comments, or code.
- Every commit — including merge commits — must be authored and committed as
  `Shahzaib Ahmad <shahzaib.ahmad97@gmail.com>`. The repository's local git
  config is set to this; do not override it per-command.
- Never mention a model name or model identifier in any repository artefact.
- Commit messages describe the change and why it was made. Imperative subject
  under ~72 characters, blank line, then prose.

## Branching

- `master` — released state. Only merges from `develop` or `hotfix/*`.
- `develop` — integration branch and repository default.
- `feature/<short-name>` — branched from `develop`, merged back into `develop`.
- `hotfix/<short-name>` — branched from `master`, merged into both.
- Never use `claude` in a branch name.

## Code style

- No explanatory comments. Names carry the meaning: if a comment is needed to
  say what code does, rename the function or variable instead.
- A short docstring is acceptable only where intent genuinely cannot be read
  from the signature. Never restate the signature in prose.
- DRY. One definition per concept.
- Optimise for clarity without adding layers. No speculative abstraction.
- Think through the architecture before adding code: keep `app/domain` pure,
  keep provider access behind `ExtractionProvider`, keep persistence in
  `app/repositories`.

## Project rules

- Model output is never written to a business record directly.
- Deterministic tests must pass with no API key. Live calls are opt-in only.
- Every state change appends an event. The event log is append-only.
- Evidence is verified by locating a verbatim quote in the source, never by
  trusting model-emitted offsets.
- No secrets and no real documents in the repository.
- `pytest` is green before every commit.

The build plan is `docs/PLAN.md`. Follow it.
