# Authorship

*Last updated: 2026-10-06*

This file documents the **human creative contribution** behind
`verification-gate-review`. Copyright protection for AI-assisted works depends on
human authorship and jurisdiction-specific originality standards; this record
distinguishes human architecture, selection, arrangement, judgment, and direction
from machine-assisted implementation. See [Why This File Exists](#why-this-file-exists).

## Human Author

**Jimmy王** (GitHub `yuye05`) — Architecture, design, product decisions, and creative direction.
Contact: 3474682031@qq.com

## Decisions

- **Config-driven single entry point.** Design the gate around one
  `gate_config.json` (the only input), rather than hard-coding per-project
  assumptions — so the skill is reusable across projects and results.
- **Three-gate architecture.** Split verification into ① numerical consistency,
  ② synthetic self-check and optional model checks, ③ adversarial review —
  three complementary evidence stages, with human review retained.
- **Built-in optical examples + a pluggable `generic_check`.** Keep the real
  built-in cases (order alignment / FFT / kurtosis) as worked examples, and add a
  config-driven `generic_check` path so *any* domain algorithm can be verified
  without bound to optical assumptions.
- **MIT license + Python-only `requirements.txt`** (`numpy`, `scipy`) — minimal,
  dependency-light distribution. (Evidence: git log, `LICENSE`, `requirements.txt`.)
- **Scope and module boundaries for the 2026 extension.** The maintainer set the
  goal of connecting the tool to formal and model-driven software engineering,
  required the existing three-layer structure to remain, and directed the work
  toward practical, reproducible improvements. The optional model-checking module
  follows that scope without introducing a new delivery stage or dependency.
  (Evidence: maintainer instructions of 2026-10-05; `references/design-notes.md`.)

## Exercise of Judgment

- **"Construct inputs per the algorithm's own assumptions"** — the configuration
  reference and built-in example docs call out that a synthetic self-check that feeds
  assumption-misaligned inputs fails on the generator, not the algorithm. Human
  judgment encoded this guardrail.
- **"Report PASS only if machine-reproducible"** — replaced eyeball/recall
  confirmation with a scripted PASS/FAIL, and treated a `B`-class (forbidden
  old-caliber) hit as HARD FAIL.
- **Refined the flow diagram into a horizontal compact layout**, and expanded the
  README with flow/decision tables, full config-field documentation, and a FAQ
  (git log: `压缩工作流程图布局为横向紧凑版`, `扩写README：流程图/判定表/配置字段/FAQ`).
- **Acceptance and publication control.** The maintainer requires observable
  validation, reviews the delivered functionality and evidence, determines the
  publication scope, and requested cleanup and documentation before the final
  submission. The acceptance evidence includes correct and defective examples,
  failure exit codes, and explicit limits on what a PASS establishes.
  (Evidence: maintainer instructions of 2026-10-05/06; `evals/check_regressions.py`.)

## Goal Setting & Direction

- **Problem:** before delivering numerical results / algorithm conclusions /
  document calibers, produce a machine-reproducible PASS/FAIL report instead of a
  human promise of "I checked it, it's fine."
- **Intended users:** math-modeling contestants and paper writers delivering
  results; anyone who needs to check numerical consistency and document the
  evidence and limits of algorithm or model checks.
- **Goals / non-goals:** config-driven, reproducible, explainable for technical
  contexts; explicitly **not** an article-structure/logic auditor (README
  *能力边界* section).
- **Research and learning direction:** connect numerical delivery checks with
  explicit requirements, finite models and counterexamples. This direction and
  the instruction to preserve the original framework were supplied by the
  maintainer; implementation details were developed with tool assistance.

## Art Direction

- **Text-first documentation**; the original compact Mermaid layout and the
  current tables express the three-layer workflow and its checks.
- **Concise tables** for decision logic (gate → result → meaning) and the
  config field reference.
- **Tone:** concise, technical, no marketing fluff — the README opens with the
  problem statement, not a tagline.

## AI Implementation

**Claude Code (Anthropic)** and **Codex (OpenAI)** assisted with code implementation,
documentation and validation under the maintainer's goals, architecture and scope
constraints. Human contributions centre on requirements, functional organisation,
research direction, review and acceptance, and final publication decisions.
Development conversation records remain local.

## Legal & Copyright

Architecture and design copyright (c) 2026-present Jimmy王.

Implementation was assisted by AI coding tools under human direction, review, and
integration. Provider output terms are recorded for transparency but are not
treated as a substitute for source provenance, license-compatibility review, or
human authorship documentation:

- **Anthropic** — commercial terms let customers retain ownership rights over
  generated outputs. (Verify current wording at the provider's published terms
  before quoting.)

### Jurisdiction framing — United States (strictest standard)

Because this is a public repo readable across jurisdictions, authorship is
documented to the **strictest** applicable bar (the US human-authorship standard):

- The US Copyright Office protects **human-authored** contributions; purely
  AI-generated material lacking human creative control is **not registrable**
  (*Thaler v. Perlmutter*; the *Zarya of the Dawn* decision; USCO reports on
  copyright and AI).
- Human **selection, arrangement, coordination**, and substantial creative
  modification of AI output **can** be protectable — the Decisions / Judgment /
  Direction sections above are the evidentiary core.
- On registration, AI-generated portions should be **disclaimed**; the claim
  covers the human-authored selection, arrangement, and modifications.

The project does not intentionally vendor GPL, AGPL, or LGPL code, and
AI-generated output is reviewed as source code — not pasted blindly — to avoid
reproducing public code without compatible licensing and required notices.

> **Not legal advice.** This record documents facts and general, widely-reported
> principles; it is not a substitute for qualified counsel in the relevant
> jurisdiction. Consult a lawyer for anything load-bearing.

## Why This File Exists

Copyright protection for AI-assisted works depends on human authorship and
jurisdiction-specific originality standards. This file documents the human
creative process behind `verification-gate-review` so the project can distinguish
human architecture, selection, arrangement, and review from machine-assisted
implementation details — and so authorship can be evidenced if ever questioned.
