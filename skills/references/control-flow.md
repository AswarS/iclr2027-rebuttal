---
name: control-flow
description: Bugs where conditional branching, gating, or path selection causes incorrect execution due to structural flaws in decision logic.
---

## Overview

Control-flow bugs arise when the branching structure of code does not faithfully represent the logical relationships between the concerns it governs. Independent concerns get accidentally coupled through shared branches, semantic distinctions get collapsed by coarse checks, and alternative code paths silently bypass shared policy enforcement.

## Patterns

### Independent Concerns Chained as Mutually Exclusive
- **When**: Two or more conditional branches (if/elif) handle logically independent transformations on the same object, and a flag can cause one branch to enter in a no-op mode while the other's work is still needed.
- **Do**: For each elif, verify that entering the preceding branch in *any* mode — including degenerate/no-op — genuinely makes the elif's work unnecessary; if the concerns are orthogonal, convert to independent if statements and add tests combining the flags governing each branch.
- **Why**: Using elif accidentally couples independent transformations, so entering one block for any reason prevents the other from running, even when it did nothing meaningful.

### Absence vs. Emptiness Conflation
- **When**: A variable can be absent/undefined (sentinel like `None`), present-but-empty (e.g., empty collection), or present-with-values, and a boolean truthiness check is used to branch between default behavior and user-provided behavior.
- **Do**: Replace truthiness checks with explicit identity checks against the sentinel value, and test all three states (absent, empty, populated) to confirm each triggers the correct branch.
- **Why**: Emptiness and absence carry different semantic intent — one is a deliberate declaration of "nothing," the other signals no decision was made — and truthiness checks collapse this distinction.

### False Uniformity in Grouped Conditions
- **When**: Multiple entity types are grouped under a single conditional branch because they share a surface-level property, but some members need special handling unconditionally while others need it only conditionally.
- **Do**: Enumerate each member of the group and independently verify whether the shared condition is valid for all of them; split into unconditional and conditional subgroups as needed.
- **Why**: A shared surface property does not imply shared behavior under all conditions, and the uniform condition silently drops necessary handling for the stricter subset.

### Asymmetric Mode Flag Application
- **When**: A mode flag governs a transformation (e.g., escaping, encoding) for the primary input but auxiliary inputs (separators, format strings, delimiters) are transformed unconditionally because their processing sits outside the conditional branch.
- **Do**: Trace every user-supplied input through the function and verify the mode flag governs the transformation for all of them; restructure into fully symmetric branches so each mode explicitly handles every input.
- **Why**: A mode flag is a contract over all outputs, and applying the transformation to even one input outside the flag's control violates user expectations.

### Special-Case Path Bypassing Shared Policy
- **When**: A special-case code path produces the same category of output as the default path but was implemented as a self-contained replacement, bypassing configuration checks or policy enforcement embedded in the default path.
- **Do**: Gate entry into the special-case path on the relevant configuration value; when the configuration disallows enriched output, fall through to the normal path which already respects the policy, and apply the fix uniformly across all entity types sharing the pattern.
- **Why**: Special-case paths written as complete replacements implicitly skip any filtering or policy checks that the default path enforces, causing configuration settings to be silently ignored.

### Disable vs. Skip Conflation
- **When**: A flag intended to disable a feature is implemented by skipping the entire code region, but that region also contains setup, cleanup, or side-effect logic needed by downstream code regardless of the feature's state.
- **Do**: Separate the feature-specific logic from the infrastructure logic so that disabling the feature skips only the feature behavior, not the surrounding bookkeeping.
- **Why**: Disabling a feature and skipping the code block that contains it are different operations when the block has responsibilities beyond the feature itself.

### Guard Shortcut with Incomplete Type Check
- **When**: An early-return guard uses a type or shape check that is correct for the common case but fails to account for subtypes, wrappers, or edge-case representations that should also pass or fail the guard.
- **Do**: Audit the guard's predicate against the full set of valid inputs, including degenerate and polymorphic cases, and widen or narrow the check to match the actual invariant.
- **Why**: Guards based on surface-level type checks can reject valid inputs or admit invalid ones when the type hierarchy is richer than the guard assumes.

### Missing Base Case in Recursive Evaluation
- **When**: A recursive or iterative property evaluation assumes all paths eventually reach a base case, but certain input structures (cycles, empty containers, degenerate nesting) cause infinite recursion or return no result.
- **Do**: Identify all terminal conditions the recursion can encounter and ensure each has an explicit base-case handler; add tests for minimal, empty, and cyclic inputs.
- **Why**: Recursive logic that lacks a base case for degenerate inputs either diverges or silently returns an incorrect default.

### Aggregate-to-Element Unrolling Mismatch
- **When**: A bulk operation is decomposed into per-element steps, and the decomposition logic does not preserve ordering, indexing, or context that the aggregate operation implicitly maintained.
- **Do**: Verify that the unrolled per-element logic reconstructs or preserves any positional or contextual information the aggregate form provided, especially at boundaries (first, last, empty).
- **Why**: Aggregate operations carry implicit context (position, neighbors, accumulator state) that per-element decomposition must explicitly replicate.

### Transformation Pipeline Ordering Sensitivity
- **When**: Multiple transformations are applied sequentially to the same data, and the correctness of a later stage depends on assumptions about what earlier stages have or have not done.
- **Do**: Document the preconditions and postconditions of each pipeline stage, and verify that reordering, inserting, or skipping a stage does not violate a downstream stage's preconditions.
- **Why**: Implicit ordering dependencies between pipeline stages create fragile coupling where any change to one stage can silently break another.

## Scenarios
- [container-vs-attribute-nullability](./scenarios/container-vs-attribute-nullability.md)
- [explicit-opt-out-vs-unset-distinction](./scenarios/explicit-opt-out-vs-unset-distinction.md)
- [validation-guard-consistency](./scenarios/validation-guard-consistency.md)
- [guard-shortcut-with-type-check](./scenarios/guard-shortcut-with-type-check.md)
- [disable-vs-skip-conflation](./scenarios/disable-vs-skip-conflation.md)
- [aggregate-to-elemental-unrolling](./scenarios/aggregate-to-elemental-unrolling.md)
- [transformation-pipeline-ordering](./scenarios/transformation-pipeline-ordering.md)
- [missing-base-case-in-recursive-property-evaluation](./scenarios/missing-base-case-in-recursive-property-evaluation.md)