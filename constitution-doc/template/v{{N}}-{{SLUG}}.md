<!-- TEMPLATE — a fixture: it stays here blank, the reference for the shape a version file keeps. Copy it to `../roadmap/v<N>-<slug>.md` to start one, then fill in the copy: replace every {{...}} with real content, add or drop Phases as the version needs, and delete all <!-- --> comments, this line included. A version's Status is recorded in `../mission.md`'s version table, not here. -->

# v{{N}} — {{VERSION_NAME}}

## Charter

<!-- What capability this version delivers: scope boundary + what this version leaves out. One or two sentences. -->
{{VERSION_SCOPE}}

## Acceptance

<!-- Executable, observable actions and results — adjectives alone do not qualify. -->
{{VERSION_ACCEPTANCE}}

<!-- A Phase is one feature. Description says in one line what it delivers — no implementation detail. -->

## Phase-1: {{FEAT_NAME}}

Status: `{{planned|in-progress|awaiting-acceptance|closed}}`

Description: {{FEAT_DESC}}

Spec: {{SPEC_PATH|non-spec}}

## Phase-2: {{FEAT_NAME}}

Status: `{{planned|in-progress|awaiting-acceptance|closed}}`

Description: {{FEAT_DESC}}

Spec: {{SPEC_PATH|non-spec}}

## Phase-3: {{FEAT_NAME}}

Status: `{{planned|in-progress|awaiting-acceptance|closed}}`

Description: {{FEAT_DESC}}

Spec: {{SPEC_PATH|non-spec}}
