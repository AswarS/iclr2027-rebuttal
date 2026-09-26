---
name: error-propagation
description: Bugs where errors, exceptions, or diagnostic information are caught, translated, reported, or recovered from incorrectly.
---

## Overview
This category covers bugs in error-handling infrastructure itself — where the mechanisms designed to catch, translate, report, or recover from failures are flawed in ways that cause crashes, misleading diagnostics, silent data loss, or misdirected user guidance. The unifying theme is that error-handling code operates on assumptions about failure modes that are narrower than reality.

## Patterns

### Overly Narrow Exception Catch in Extensible Context
- **When**: An error recovery handler catches a specific exception subtype, but the guarded code includes user-extensible entry points (plugins, hooks, converters) that can raise the broader parent type.
- **Do**: Trace all code paths within the guarded block — especially extensible ones — and widen the catch to the appropriate hierarchy level that covers all semantically valid exception types from both internal and external code.
- **Why**: Treating an extensible subsystem as closed causes the handler to miss exception types that user-supplied code legitimately raises.

### Fallback Code Reusing the Failed Abstraction Layer
- **When**: Error-handling or diagnostic code accesses attributes or methods on an object that has already demonstrated broken behavior (e.g., its string representation or attribute access protocol threw an exception).
- **Do**: Replace instance-level operations with lower-level primitives that bypass the object's customizable protocols (e.g., use the language's type introspection builtins instead of instance attribute access), ensuring the fallback cannot fail for the same reason as the original code.
- **Why**: Error-handling code that uses the same abstraction layer as the code it recovers from creates recursive failure — the fallback breaks in the same way the original operation broke.

### Misleading Error Message Suggesting Incomplete Alternatives
- **When**: An error message recommends an alternative approach, but the suggestion only works for a subset of the use cases that trigger the error, or omits a supported path that solves the user's actual need.
- **Do**: Enumerate all distinct use cases that trigger the error and verify the suggested alternative works for each; list multiple alternatives with context about when each applies, distinguishing imperative from declarative mechanisms when their execution-time semantics differ.
- **Why**: Developers model the most common misuse case when writing the message, not realizing other legitimate scenarios exist where the suggested alternative is insufficient.

### Scope-Causation Conflation in Diagnostic Messages
- **When**: A catch block constructs an error message using variables that are in scope but not necessarily causally related to the exception, especially when a generic exception type can be raised by multiple operations within the guarded block.
- **Do**: Verify each variable in the message is causally tied to the failure; either narrow the guarded block to one failure mode or rewrite the message to describe only what is definitively known.
- **Why**: Variables in scope at an exception site are correlations, not causes — reporting them as causes produces misleading diagnostics that direct users to investigate the wrong entity.

### Stale API References in Diagnostic Hints
- **When**: A user-facing error hint references type names, parameters, or API constructs that were valid when written but have since been renamed, deprecated, or restructured.
- **Do**: Cross-reference every identifier in diagnostic messages against the current public API; add tests asserting exact hint wording so API evolution triggers failures when hints become stale.
- **Why**: Error message strings escape normal refactoring discipline, so they drift out of sync with the API they describe, giving users guidance that doesn't work.

### Silent Exception Swallowing in Resilient Dispatch
- **When**: A "robust" dispatch pattern catches exceptions to prevent one component's failure from crashing the pipeline, but the caught exceptions have no path to logging or monitoring.
- **Do**: Add structured logging with full traceback at the catch site while preserving the existing error-as-return-value behavior — control-flow recovery and diagnostic visibility are independent concerns that must both be satisfied.
- **Why**: Converting an exception to a return value feels like handling it, but unless something logs or reports it, the failure becomes invisible and repeated silent failures accumulate undetected.

### Incomplete Exception Translation Boundary
- **When**: An abstraction layer translates dependency exceptions into library-owned types, but handlers were added incrementally as specific exceptions were encountered rather than by systematically enumerating the dependency's full exception set.
- **Do**: Audit the dependency's complete exception hierarchy, map every unmapped type to a semantically appropriate abstraction-level exception, and add a catch-all on the dependency's base exception as a safety net to seal the boundary against future additions.
- **Why**: Incremental, encounter-driven handler addition conflates "exceptions observed so far" with "exceptions that can occur," leaving gaps that leak dependency internals to consumers.

## Scenarios
- [iterator-exhaustion-handling](./scenarios/iterator-exhaustion-handling.md)
- [untrusted-input-boundary-validation](./scenarios/untrusted-input-boundary-validation.md)
- [graceful-fallback-for-domain-restricted-optimization](./scenarios/graceful-fallback-for-domain-restricted-optimization.md)
- [exhaustive-fallback-chain](./scenarios/exhaustive-fallback-chain.md)
- [validation-funnel-safety-assumption](./scenarios/validation-funnel-safety-assumption.md)
- [validate-before-catch](./scenarios/validate-before-catch.md)
- [error-reporting-channel-selection](./scenarios/error-reporting-channel-selection.md)
- [incomplete-abstraction-boundary](./scenarios/incomplete-abstraction-boundary.md)