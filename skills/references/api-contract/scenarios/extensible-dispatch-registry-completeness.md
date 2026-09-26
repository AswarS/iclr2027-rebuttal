## Problem Description

When a system uses a dispatch registry (e.g., a dictionary mapping operation names/types to handler functions) to route simplification, transformation, or processing logic, new operations or expression types can be introduced over time without corresponding handlers being added. Because the dispatch mechanism typically fails silently — returning the input unchanged rather than raising an error — these missing handlers create invisible bugs where the system appears functional but produces unsimplified, incorrect, or incomplete results. This is especially insidious when the missing operation belongs to a well-known family of related operations where most siblings already have handlers, giving users the false impression of complete coverage.

## Root Cause Analysis

The fundamental issue is an **implicit completeness assumption** about an **extensible registry**. When developers initially build a dispatch table, they populate it with all known operations at that point in time. However, the registry is not a closed system — the expression language it serves evolves as new functions, types, or operations are added. The registry lacks a mechanism to enforce that every dispatchable operation has a handler, so gaps accumulate silently.

Three factors compound this:

1. **Silent no-op fallback**: The dispatch mechanism returns the input unchanged when no handler is found, rather than raising an error or warning. This means the failure mode is *wrong or incomplete output*, not a crash — making it far harder to detect.
2. **Output-side blindness**: Developers typically think about which operations appear in *input* expressions, but transformation passes can produce *new* operations in their output (e.g., a rewrite rule that introduces `arg()` while simplifying `abs()` or `sign()`). These output-side operations are systematically overlooked when auditing registry completeness.
3. **Family fragmentation**: Mathematical and logical operations come in conceptual families (e.g., `abs`, `sign`, `re`, `im`, `arg` for complex number operations). Handlers are often added piecemeal — a developer implements the ones they need and moves on, leaving siblings unhandled without documentation of the gap.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - A simplification or transformation pass returns its input unchanged (silent no-op) for a specific operation, while correctly simplifying closely related operations
  - Wrong or unsimplified output rather than an error or exception — the system "works" but produces suboptimal results
  - The problematic operation belongs to a recognizable family where sibling operations are handled correctly
  - The issue may surface only when a preceding transformation pass introduces the unhandled operation into an intermediate expression

### 解决步骤
1. **Confirm the dispatch miss**: When a transformation produces an unexpected no-op, inspect the dispatch registry (dictionary/map) to verify whether the operation in question has a registered handler. Search for the operation's key (string name, type, or class) in the registry.
2. **Audit the operation family**: Enumerate all members of the same conceptual group (e.g., all complex-number functions, all trigonometric functions, all bitwise operations). For each member, verify that a handler exists in the registry. Document any gaps found.
3. **Study existing handler patterns**: Examine 2–3 existing handlers for sibling operations to understand the function signature, return conventions (e.g., return `None` for unhandled sub-cases), and how they interact with the surrounding context (assumptions, domains, etc.).
4. **Implement the missing handler**: Write the new handler following the exact pattern of its siblings. For cases where the context is insufficient to simplify (e.g., no assumptions about the variable), return `None` or the appropriate sentinel to indicate "no simplification possible." For cases where simplification is unambiguous, return the simplified result.
5. **Register the handler**: Add the new handler to the dispatch dictionary using the same key convention as existing entries. Ensure the registration happens at module load time or during the same initialization phase as other handlers.
6. **Add regression tests**: Write tests covering both the case where simplification should occur and the case where the handler correctly declines to simplify (returns the input unchanged due to insufficient information).

### Why This Works

The fix directly addresses the root cause by extending the dispatch table to cover the missing case, restoring the implicit completeness invariant. By following the established handler pattern — simplify when semantics are unambiguous, return `None`/sentinel when context is insufficient — the new handler maintains safety (no incorrect simplifications) while enabling correctness (simplification happens when it should). The family audit step prevents the same class of bug from recurring for other siblings.

## Boundary Cases
- **Handler that should intentionally not exist**: Some operations in a family may genuinely not need a handler (e.g., they are always rewritten to other forms before reaching the dispatch point). These should be explicitly documented in a comment near the registry to distinguish intentional omissions from accidental gaps.
- **Operations appearing only in intermediate output**: An operation may never appear in user-facing input but can be introduced by an earlier transformation pass. These are the most commonly missed and should be audited by tracing the output types of all registered handlers.
- **Handlers that return identity vs. handlers that return None**: Ensure the convention is consistent — returning the input unchanged and returning `None` (meaning "I don't handle this") may have different downstream effects depending on the dispatch framework.
- **Overlapping registries**: In systems with multiple dispatch tables (e.g., one for simplification, one for evaluation, one for code generation), a new operation must be registered in *all* relevant tables, not just the one where the bug was first observed.
- **Dynamic or plugin-based operation sets**: If operations can be added via plugins or extensions, the registry completeness problem becomes structural. Consider adding a validation step that checks all registered operations against all dispatch tables at startup or test time.

## PR Examples
- sympy__sympy-21055: The `arg` (complex argument) function was missing from a rewrite/simplification dispatch dictionary, while sibling functions like `abs`, `sign`, `re`, and `im` all had handlers. The system silently returned unsimplified expressions involving `arg`, producing wrong output without any error signal.