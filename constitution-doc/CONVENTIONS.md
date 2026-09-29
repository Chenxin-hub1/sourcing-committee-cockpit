# Conventions

Method, not project content: a project's own rules live in its own docs. Improve a convention here and the next project's re-run offers it.

Every doc here has a blank in [`template/`](template/): a reference for the shape a doc keeps, and a starting point when copying one helps — a default to depart from where the project needs it. The blanks are fixtures: they stay, and none counts as a doc of its kind.

## Roadmap

- **One version, one file**, at `roadmap/v<N>-<slug>.md`. A version is the shipping unit and a **Phase is one feature**; a file holds those two levels and no more, and **one Phase maps to one spec** — write `non-spec` when it needs none. Task-level progress belongs to issues.
- **The version file's shape** is [`template/v{{N}}-{{SLUG}}.md`](template/) — copy it to `roadmap/v<N>-<slug>.md` to start one.
- **A version's Status is recorded only in [`mission.md`](mission.md)'s version table**; a version file carries Phase `Status:` alone.
- At most three files in `roadmap/`, at most one version `in-progress`.
- Once every Phase in a version is closed, move its file to the archive and drop its row from the mission table; `roadmap/` carries only what is still ahead.
- **A distant version is a guess, not a plan.** At each version close, review the remaining version files: keep what still holds, delete the file of what has been overtaken.
- **Closing a Phase is the sweep clock.** When a Phase turns `awaiting-acceptance`, search this folder for every ticket number it closed and rewrite each "pending, see ticket NN" into its answer, or re-point it at the ticket that now owns the question. A dangling pointer is the failure the sweep exists to catch.
