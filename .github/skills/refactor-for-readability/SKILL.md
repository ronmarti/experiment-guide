---
name: refactor-for-readability
description: Refactor existing code into cohesive, injectable classes and readable control flow while preserving behavior and improving tests and documentation.
---

# Refactor for readability

Use this skill when restructuring code for maintainability, readability, or
testability without intentionally changing its behavior.

## Understand before changing

1. Read the relevant product requirements, source, tests, and existing project
   conventions. Identify responsibilities, long methods, repeated logic, and
   deeply nested control flow.
2. Record the behavior that must remain unchanged, including persisted formats,
   ordering, errors, asynchronous work, and user-facing interactions where
   applicable. Preserve existing work in the working tree.
3. Make an incremental plan around real responsibilities, not line counts.

## Structure and dependencies

- Organize source by function, such as UI, model, and business logic. Keep each
  production class in its own file and give it one clear responsibility.
- Prefer cohesive classes with focused methods for business behavior. Use
  dependency injection at boundaries such as external clients, clocks, and ID
  generators so behavior can be tested independently.
- Follow DRY and KISS: reuse shared logic, but avoid speculative abstractions,
  duplicated state, and indirection that makes the code harder to follow.
- Respect framework conventions. Keep required functional components and hooks
  in the framework's supported form; delegate complex behavior to injectable
  classes instead of forcing an incompatible class-based UI.
- Keep names descriptive enough that ordinary method calls need no explanation.

## Make the flow linear

- Replace deeply nested conditionals with clear validation gates, guard clauses,
  early returns, or `continue` where they make the normal path easier to read.
- Extract coherent phases into named methods. Flatten repeated nested traversal
  with a shared iterator where it improves clarity.
- Keep loops nested when their relationship is essential. Do not separate
  dependent passes if doing so changes ordering, error precedence, atomicity,
  resource lifetime, or behavior. These validation gates are not concurrency
  semaphores; use synchronization primitives only when synchronization is needed.

## Explain intent

- Give every application class and method a concise summary docstring describing
  its purpose or contract, including important side effects or return behavior.
- Review code in roughly 5-10-line logical chunks and add comments only when
  they clarify non-obvious intent, invariants, tradeoffs, or complex control
  flow. Explain why the block exists, not each obvious operation or method call.
- Keep comments accurate and close to the code they explain; remove or update
  comments made obsolete by the refactor.

## Verify

- Rework tests around the extracted classes and inject fakes for external
  dependencies. Retain integration and UI tests for behavior that crosses
  boundaries; add focused cases for any changed behavior or uncovered risk.
- Run the smallest relevant test set, expanding it when the refactor spans
  multiple responsibilities. Run the existing build or type checks when
  applicable, and verify persisted formats and workflows remain compatible.
- Update directly affected documentation. Report what changed, what was
  verified, and any limitations; do not claim unperformed validation.
