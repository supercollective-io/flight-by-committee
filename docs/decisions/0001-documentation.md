# ADR 0001: Keep documentation lean and close to decisions

Status: **Accepted** · Date: 2026-11-05

## Context

This is a software project in early exploration. We want to preserve useful research and reasoning without creating a separate documentation project. The project owner has requested a lean, single-source approach that allows decisions to change easily.

## Decision

Keep Markdown in the repository, with one home for each topic:

- The documentation README introduces the project and links to the notes.
- The plan holds next steps and experiments.
- Each ADR holds a significant choice, its rationale and relevant research. Distinguish source findings, our interpretation and proposed behaviour.
- Code and tests define implemented behaviour. Add reference documentation where readers need an explanation; derive structural details from code or schemas where practical.

Link rather than duplicate. Edit proposed ADRs freely. When a choice is made, mark it **Accepted** and date it; acceptance does not imply implementation. Use Git history for routine evolution once Git is set up. For a substantial reversal of an accepted choice, add a replacement ADR and mark the old one **Superseded**, linking both. Ordinary implementation details do not need ADRs or a separate approval process.

Add verified setup/run instructions when software works, a short protocol reference when the contract settles, and a tested operator guide before a show. Update affected docs with behaviour changes and check links and runnable examples using the project's tooling. Use British English and metric units while preserving literal API identifiers.

## Research and trade-offs

[Diátaxis](https://diataxis.fr/) separates learning, procedures, reference and explanation. [Write the Docs](https://www.writethedocs.org/guide/docs-as-code/) integrates documentation with development. [ADR guidance](https://adr.github.io/) supports concise decision records. These sources were checked on 5 November 2026; we apply them proportionately rather than adopting a full documentation framework.

This keeps maintenance small, but depends on updating canonical notes instead of accumulating conflicting copies. A documentation site, separate manuals and multi-version publishing add overhead before we have a demonstrated need.

## What would change this

Expand the structure when contributors, operators or multiple supported releases cannot find the information they need. Add only what resolves that problem.
