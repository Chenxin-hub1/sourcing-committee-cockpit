# mattpocock-skills: project overrides

Read before running any skill named below. Where this file and the skill's own instructions disagree, this file wins.

## to-spec

- **Default triage label is `ready-for-human`**, overriding the `ready-for-agent` the skill's own instructions apply.
- Once the spec is published, ask the user whether it will be broken into tickets — the split is the user's call; run to-tickets only on a yes.
  - Answer is **yes** → leave the spec at the default `ready-for-human`; the tickets carry their own labels.
  - Answer is **no** → the spec itself is the work item; relabel it `ready-for-agent`.

## to-tickets

- Every ticket carries a `**Type:**` line right below `**Status:**`. Known types: `task`, `research`, `grilling`, `prototype` — coin a new type when a ticket fits none of these.
- `Status:` follows the acceptor — the executor is the other side: a human acceptor makes the ticket `ready-for-agent`; a ticket only a human can carry out is `ready-for-human`.

## grilling

Put questions to the user through Claude Code's built-in question tool (`AskUserQuestion`) — don't ask in plain chat text. The tool accepts at most 4 questions per call, so a wider round goes out as consecutive calls — batch it, don't trim it.

## implement

When an issue is done, leave a comment on it stating exactly which commits implemented it (list the commit hashes).

## teach-skills

Every file the teach skills generate goes under `.skills-doc/teach/` — nowhere else — and that folder must be git-ignored (add if missing).
