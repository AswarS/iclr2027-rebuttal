## Problem Description

A serialization or code-generation system that tracks dependencies (e.g., imports) for each emitted reference contains special-case handling for well-known symbols. These special cases emit shorthand references but declare an empty or incomplete set of required imports, relying on the **coincidental assumption** that some other serialized element in the same output will always contribute the needed import. This assumption holds in the vast majority of cases—until an edge case arises where the special-cased symbol is the *only* reason that import is needed, at which point the generated output is missing a critical dependency and fails at runtime.

## Root Cause Analysis

The fundamental contract of a dependency-tracking serializer is that **every emitted reference is a self-contained unit that independently declares all imports required to resolve itself**. When a developer adds a special-case shortcut path (e.g., recognizing a well-known default value and emitting a short alias), they observe that the required import is "always already present" in practice—contributed by other serialized fields, base classes, or related elements that happen to share the same module. This observation leads to the cognitive trap of **conflating "usually already present" with "always already present."**

The special case returns the symbolic reference string but declares an empty (or incomplete) dependency set, silently breaking the self-sufficiency contract. The bug is latent: it passes all existing tests because those tests always include other elements that coincidentally provide the missing import. It only surfaces in rare but valid configurations where the special-cased symbol is the sole contributor of that particular import—a scenario that may not exist in the test suite but absolutely exists in production.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **crash-exception**: Generated code (e.g., migration files, serialized configurations) raises `ImportError`, `NameError`, or similar resolution failures at load time
  - **wrong-output**: Generated output is syntactically valid but missing an import statement, causing failures only when executed in isolation or in specific rare configurations
  - The failure is intermittent or configuration-dependent—most generated outputs work fine, but certain minimal or unusual combinations break

### 解决步骤
1. **Audit all special-case / shortcut paths in the serializer**: Enumerate every branch where the serializer recognizes a well-known symbol and emits a shorthand reference instead of following the general-purpose serialization path.
2. **Verify self-sufficiency of each path's dependency declaration**: For each special-case branch, confirm that the returned dependency set (imports, includes, etc.) contains *everything* needed to resolve the emitted reference string. Do not assume any other serialized element will contribute the import.
3. **Fix incomplete declarations**: Where a special case returns an empty or partial dependency set, add the missing imports/dependencies so the reference is fully self-contained. This may mean declaring an import that is "usually redundant"—redundancy is harmless, omission is not.
4. **Write isolation test cases**: For each special-case path, construct a test where the special-cased symbol is the *only* element requiring a particular import. No other serialized element in the test should coincidentally contribute that same import. Verify the generated output is complete and executable.

### Why This Works

The fix restores the fundamental invariant: **every serialized reference independently declares its own dependencies**. Redundant declarations are collapsed or deduplicated by the output layer (e.g., duplicate import statements are merged), so there is zero cost to being self-sufficient. The isolation test cases ensure the invariant is enforced even in edge configurations, preventing future regressions from the same cognitive trap.

## Boundary Cases

- **Symbol is the sole representative of its module**: The special-cased symbol comes from a module that no other field, validator, default, or base class in the generated output references. This is the primary trigger for the latent bug.
- **Multiple special cases sharing the same missing import**: If several shortcut paths all omit the same import, fixing only one may mask the remaining broken paths. Each must be independently audited and fixed.
- **Nested or transitive dependencies**: The special-cased symbol may require not just a direct import but also a transitive dependency (e.g., a module that must be importable for the reference to resolve). Ensure the full dependency chain is declared.
- **Serializer used in isolation vs. in aggregate**: The bug may only manifest when the serializer's output for a single element is used standalone (e.g., a migration file with a single operation), not when aggregated with many elements that mask the missing import.
- **Future additions of new special cases**: Any new shortcut path added to the serializer must be reviewed against this same contract. The pattern is easy to re-introduce if developers copy the style of existing (previously broken) special cases.

## PR Examples

- **django__django-14580**: A migration serializer's special-case handling for well-known default values emitted a reference string but declared an empty import set, assuming other serialized model fields would always contribute the necessary import. In edge cases where no other field required that import, the generated migration file was broken.