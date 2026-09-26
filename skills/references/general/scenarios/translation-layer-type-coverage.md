## Problem Description

Translation/serialization layers that use per-type dispatch patterns (e.g., `_print_X`, `_serialize_X`, `_convert_X`) to convert expressions from one representation system to another are inherently incomplete by design. When a source expression type lacks a corresponding dispatch handler, the system silently falls back to a generic/default handler that emits output in the **source** system's representation rather than valid **target** syntax. This produces subtly incorrect output — syntactically plausible but semantically wrong in the target language — without any error or warning, making the coverage gap invisible until downstream consumers fail or produce wrong results.

## Root Cause Analysis

The fundamental issue is an **open-ended dispatch architecture without completeness enforcement**. Per-type dispatch translators grow incrementally as developers encounter new expression types, but there is no compile-time check, schema validation, or runtime assertion that guarantees all source types have corresponding target handlers. The problem is compounded by two reinforcing factors:

1. **Silent fallback masking gaps**: The default/generic handler produces *some* output for any input, creating a false sense of correctness. If the fallback raised an error, the gap would be immediately obvious.

2. **Coverage completeness bias**: Developers naturally assume the set of types they've explicitly handled constitutes sufficient coverage, especially when existing tests pass. New types added to the source system, or rarely-used existing types, slip through unnoticed because nothing in the architecture forces attention to them.

The result is that structurally similar constructs (e.g., `Sum`, `Product`, `Integral` in a symbolic math system) may have inconsistent handling — some correctly translated, others silently falling through to invalid output — creating a patchwork of correctness that is difficult to audit by inspection alone.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Output from the translation layer contains syntax or identifiers from the **source** representation system rather than valid **target** syntax
  - Structurally similar expression types produce inconsistent output formats (some correctly translated, others not)
  - Round-trip conversion fails silently — the target system cannot parse or correctly evaluate the translated output
  - No errors or warnings are raised despite producing invalid target-language output

### 解决步骤
1. **Audit dispatch coverage**: Enumerate all expression types in the source system that have meaningful counterparts in the target system. Diff this list against the set of implemented dispatch handlers to identify gaps.
2. **Harden the fallback handler**: Modify the default/generic handler to raise an explicit `NotImplementedError` (or equivalent) for unhandled types, rather than silently emitting source-system representation. This converts future coverage gaps from silent bugs into immediate failures.
3. **Implement missing handlers**: For each identified gap, add the appropriate dispatch method that translates the source type into the target system's equivalent syntax.
4. **Follow existing conventions**: Study how structurally similar types are already handled (e.g., wrapping in evaluation-prevention constructs, applying specific formatting patterns) and apply the same conventions to new handlers for consistency.
5. **Add targeted tests**: Write output-comparison or round-trip tests for each new handler, verifying the translated output is valid and correct in the target system. Include tests for edge cases like nested expressions and boundary arguments.

### Why This Works

The core fix addresses the problem at two levels. **Tactically**, adding the missing handler closes the immediate gap. **Structurally**, making the fallback noisy transforms the architecture from one that silently degrades to one that fails fast on coverage gaps. This is critical because per-type dispatch translators will always face the incremental-coverage problem — new types will be added to the source system over time. A noisy fallback ensures that each new gap is discovered at the moment it first occurs, rather than lurking as a silent correctness bug. Following existing conventions for peer constructs ensures semantic consistency across the translation layer, preventing subtle behavioral differences between similar expression types.

## Boundary Cases
- **Types with no target equivalent**: Some source types may have no meaningful counterpart in the target system. The fallback should still raise an error, but the error message should distinguish "not yet implemented" from "fundamentally unsupported."
- **Nested/composed expressions**: A newly handled type may appear inside other expressions. Tests must verify that the handler works correctly when the expression is nested within other translated constructs.
- **Target-system-specific wrapping**: Some target systems require evaluation-prevention wrappers (e.g., `HoldForm` in Mathematica) for symbolic constructs. Missing this wrapping produces output that evaluates to a numeric result rather than remaining symbolic, which is a subtle semantic error even when the syntax is valid.
- **Parameterized expressions**: Handlers must correctly translate all arguments/parameters of the source expression, not just the primary operand (e.g., summation bounds, integration variables).
- **Backward compatibility**: Making the fallback noisy may break existing workflows that unknowingly depend on the silent (incorrect) output. Consider a deprecation warning phase before hard errors.

## PR Examples
- sympy__sympy-12171