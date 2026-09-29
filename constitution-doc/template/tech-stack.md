<!-- TEMPLATE — when filling in: replace every {{...}} with real content, delete the blocks this project has nothing for, and delete all <!-- --> comments, this line included. Defaults come from the manifests (pyproject / package.json / compose) and the stack module blocks /setup-project appends at the end of this file — they stay as the conventions the code follows; the table above records the decisions. -->

# Tech stack

<!-- The architecture in one line, e.g. "server-side TypeScript app, SSR, single-node SQLite". -->
{{ARCHITECTURE_ONE_LINER}}

## Core

<!-- One row per layer. Rationale is why this table exists — drop a row that has none, the manifest already said it. -->

| Layer | Choice | Rationale |
| --- | --- | --- |
| Language | {{LANGUAGE}} | {{RATIONALE}} |
| Runtime | {{RUNTIME}} | {{RATIONALE}} |
| Framework | {{FRAMEWORK}} | {{RATIONALE}} |
| Data | {{DATABASE}} | {{RATIONALE}} |
| Testing | {{TEST_FRAMEWORK}} | {{RATIONALE}} |

## Deployment

<!-- Where it runs and how it ships — the part the code does not show. -->
{{DEPLOYMENT}}

## Ruled out

<!-- What a reader would reasonably reach for, what carries that job here instead, and one line of reason. "Not yet" says what would flip it. A decision with a long argument behind it points at its ADR. -->

- {{RULED_OUT}} — {{WHAT_CARRIES_IT_INSTEAD}}, {{REASON}}
