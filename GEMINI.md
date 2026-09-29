<!-- module:constitution -->
# Constitution

Constitution docs live in `constitution-doc/`; `README.md` indexes them. Load the section a task names. Placeholders are gaps, not facts: a `{{...}}` standing where you needed an answer means that part is unwritten — say so and offer to fill it.

- **Before a plan or the first edit of a task**: read the `roadmap/` file that `mission.md`'s `in-progress` row points at. Set the Phase you are starting to `Status: in-progress`; before reporting completion set it to `awaiting-acceptance`, run the retirement sweep (`CONVENTIONS.md`, Roadmap), and request acceptance.
- **Before editing `constitution-doc/`**: read `CONVENTIONS.md`.
- **Writing a doc here**: `template/` holds each doc's blank — reference for the intended shape; copy it to start one, and depart from it where the project needs it. The blanks stay.
- **When the ask reaches past the current version** — new scope, a priority call, a "is this worth building": read `mission.md` before answering.
- **Before writing code, adding a dependency, swapping a framework, or changing how it deploys**: read `tech-stack.md` — choices, the stack conventions the code follows, deployment, what is ruled out.
- **Edits that wait for the user**: `closed`, versions and Phases, `mission.md`, and `tech-stack.md`'s "Ruled out".
- **A doc that disagrees with the code or with reality**: stop and surface it.
<!-- /module:constitution -->

<!-- module:language -->
# Language

Language follows the audience:

- Audience includes the user — replies, plan/design explanations, code comments, and any doc read by both agents and the user (README, design docs, skill notes): 中文.
- Audience is code, business, or an agent — identifiers, error messages, logs, code output, UI copy, business-facing text, subagent prompts, workflow instructions: English.
<!-- /module:language -->

<!-- module:vibe-coding -->
# Vibe coding: technical reference

- API facts (existence, signature, deprecation): the installed package is the
  authority. Not installed? Fall back to official docs for the candidate version,
  and tell the user explicitly that it is unverified against an installed package.
- Concepts & patterns: skill (project → plugin → bundled in package) → context7
  → official docs. A source that is silent, unavailable, or tracking a different
  version doesn't count — move down the list.
- API facts inside a concept answer still get checked against the installed package.
<!-- /module:vibe-coding -->

<!-- module:mattpocock-rules -->
# mattpocock-skills

Every file this skill set generates goes under `.skills-doc/`, never the repo root; keep the project CLAUDE.md pointing at the real paths.

Don't pick up an issue on your own initiative in a session that is already doing something else.

**Before running to-spec, to-tickets, grilling, implement, or a teach skill**: read `constitution-doc/mattpocock-rules.md` — it overrides those skills' own defaults (triage labels, ticket fields, how questions reach the user, what a finished issue records).
<!-- /module:mattpocock-rules -->

<!-- module:design -->
# Design files

`.design/` holds presentation material: mockups, diagrams, prototypes.

- **Showing one**: open it locally for the user, never as a claude.ai Artifact.
- **Generated diagrams**: edit the spec and regenerate; the HTML is output.
- **Implementation reference**: only a figure a constitution doc links; the rest is presentation, the doc is the truth.
<!-- /module:design -->
