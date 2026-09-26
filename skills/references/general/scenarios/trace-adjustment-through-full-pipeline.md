## Problem Description

This pattern occurs when an adjustment value (such as an offset, padding, or correction factor) is incorporated into a computed dimension at one stage of a processing pipeline, and then the same adjustment is redundantly applied again at a later stage. The result is a **double-counting** of the adjustment, producing incorrect output (e.g., misalignment, wrong dimensions, shifted positions). The bug is often masked in one of several parallel code branches due to an independent inconsistency—such as one branch hardcoding zero where it should return the real offset—causing the double-count to cancel out in that branch while manifesting as a visible error in the other.

## Root Cause Analysis

The underlying principle is **loss of provenance across transformation boundaries**. When a value passes through multiple stages—construction, return, layout, rendering—each stage's developer may independently reason that "this value needs adjustment X" without verifying whether a prior stage already absorbed X into the value. This is a form of implicit coupling: the upstream stage silently embeds the adjustment into a dimension, but this embedding is not surfaced in the API contract (e.g., via naming, documentation, or explicit metadata), so downstream stages treat the value as unadjusted and apply the correction again.

The problem is compounded by **symmetry-breaking across parallel branches**. When two sibling code paths (e.g., two rendering modes, two element types) should return equivalent metadata but one returns the real offset and the other returns zero, the inconsistency creates a situation where:

- In the branch returning zero, the downstream double-count has nothing to double, so the output appears correct (accidentally).
- In the branch returning the real value, the double-count produces a 2× error, but developers may attribute the discrepancy to the branch itself rather than to the shared downstream logic.

This combination—double-counting plus inconsistent parallel branches—delays detection and misdirects diagnosis.

## Solution Strategy

### 识别信号
- 观测到的现象: Visual misalignment, incorrect centering, or wrong spatial dimensions that appear **only in one rendering mode or element type** but not another. Output values that are off by exactly 1× or 2× a known adjustment constant. Test failures showing `wrong-output` where the error magnitude matches a specific offset value.

### 解决步骤
1. **Trace the adjustment end-to-end**: Starting from where the offset/adjustment is first computed, follow it through every function return, intermediate variable, and downstream consumer. Build a map of every point where the value is read or arithmetically applied.
2. **Identify double-counting sites**: If the adjustment was embedded into a dimension during construction (e.g., added to height at creation time), check whether any downstream formula subtracts or adds the same value again. If so, the adjustment is applied twice—flag this as the primary bug.
3. **Audit parallel branches for consistency**: Enumerate all sibling code paths that construct equivalent elements (e.g., different rendering backends, different symbol categories). Verify that each branch returns the same offset metadata. A branch returning zero or a hardcoded value where others return the real computed offset indicates a copy-paste error or oversight—flag this as a secondary bug.
4. **Remove the redundant downstream application**: Eliminate the adjustment from the later pipeline stage where it was double-counted. Preserve it at the original construction step where it was first embedded—this is the canonical application point.
5. **Fix inconsistent parallel branches**: Ensure all sibling branches return the correct offset metadata so that the single downstream application point works uniformly across all paths.
6. **Handle discrete/mode-specific edge cases**: After removing the double-count, check whether any rendering mode relied on the accidental extra adjustment to compensate for a separate issue (e.g., integer-grid rounding requiring a +1 correction). If so, add an explicit, well-commented, mode-specific fix rather than leaving the double-count in place.
7. **Verify across all branches and modes**: Test every parallel code path and rendering mode to confirm the fix is universal and no branch regresses.

### Why This Works
The fix enforces the principle that **each adjustment must be applied at exactly one well-defined point in the pipeline**. By tracing the offset from origin to all consumers, you establish a single source of truth for where the correction lives. Removing the redundant application eliminates the 2× error, and harmonizing parallel branches ensures the fix is not mode-dependent. Explicit handling of discrete edge cases prevents the removal of the double-count from unmasking a separate latent bug that the double-count was accidentally compensating for.

## Boundary Cases
- **Accidental compensation**: Removing the double-count may expose a previously hidden bug in a specific rendering mode that the extra adjustment was accidentally masking. Always check for mode-specific corrections needed after the fix.
- **Zero-offset branches**: A parallel branch that hardcodes zero offset may appear correct before and after the fix, but it is still semantically wrong—it should return the real offset so that future downstream changes don't re-introduce asymmetry.
- **Chained pipelines**: In deeply nested pipelines (3+ stages), the adjustment may be applied at more than two points. The full trace must cover all stages, not just the first two.
- **Negative/inverse adjustments**: The double-counting may manifest as a subtraction applied twice (yielding −2× offset) rather than an addition, making the error direction non-obvious without careful sign tracking.

## PR Examples
- sympy__sympy-16503