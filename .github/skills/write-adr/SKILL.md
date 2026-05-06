# Skill: write-adr

Recipe for capturing an Architecture Decision Record.

## When to write an ADR

Write a new ADR if the change you are proposing involves any of:

- Adding, replacing, or removing a service, library, or external dependency.
- Changing the data model (tables, columns, fact/dim structure).
- Changing how a tax rule (DK or DE) is interpreted in code.
- Changing an integration pattern (push vs pull, sync vs async, batch vs stream).
- Changing a security or privacy boundary (who/what can see which data).
- Changing the deployment architecture (host, runtime, image base, secrets handling).

Bug fixes, refactors that preserve behavior, doc updates, and test additions do **not** require an ADR.

If unsure: write one. ADRs are cheap; missing context is expensive.

## Steps

1. **Branch:** `docs/<issue-number>-adr-<slug>` or attach the ADR to the implementation branch if it ships in the same PR.
2. **Filename:** `docs/decisions/NNNN-kebab-case-title.md`. Use the next free integer (zero-padded to 4 digits). Never reuse a number.
3. **Copy the template:** start from `docs/decisions/adr-template.md`.
4. **Fill in the sections:**
   - **Status:** start as `Proposed`. Becomes `Accepted` on PR merge.
   - **Context:** *why are we deciding this now?* What forces are in play?
   - **Decision:** the chosen option, in plain language.
   - **Consequences:** what becomes easier; what becomes harder; what we now have to maintain.
   - **Alternatives considered:** at least one. Explain why it lost.
5. **Link from the PR description.**
6. On merge, status flips to `Accepted`. If superseded later, the new ADR adds `Supersedes ADR-XXXX` and the old one becomes `Superseded by ADR-YYYY`.

## Style

- Length: ½ to 2 pages. If you need more, the decision is too big and should be split.
- Past tense for context, present tense for the decision, conditional for consequences.
- Diagrams (Mermaid) are welcome where they reduce text.
- Link to relevant code, runbooks, or external references.

## Anti-patterns

- ADRs that rationalize a decision after the fact without recording the alternatives. Always include alternatives.
- ADRs that read like marketing copy. State the trade-offs honestly, including what we are giving up.
- ADRs that list implementation details ("we will use a `Decimal(20,4)` column"). Implementation details belong in code; ADRs are about *why*.
