## Problem Description

When an upstream language runtime or framework changes the semantics of metadata fields on its data structures — specifically which source line a composite AST node reports as its primary `lineno` — downstream code that builds boundary maps (statement start/end line ranges) from those fields silently degrades. The boundary map develops gaps where sub-elements (e.g., decorators, annotations) no longer contribute entries, causing the preceding statement's computed range to bleed past its actual end into the next construct's prefix lines. This manifests as incorrect error messages, inflated source excerpts, or diagnostic output that includes extra unrelated lines — but only on newer runtime versions where the representation shift occurred.

This is a general instance of **upstream representation shift at a boundary seam**: any time downstream logic implicitly assumes that a metadata field's scope or coverage is stable across versions, a subtle narrowing of that field's semantics can silently break boundary computations without raising any explicit error, because the field still exists and returns a valid value — just one with a different meaning.

## Root Cause Analysis

The underlying principle is an **implicit assumption violation** about the stability of upstream metadata semantics. The downstream AST walker assumes that each node's `lineno` attribute encompasses all of its syntactic constituents — including prefixed sub-elements like decorators. When the upstream runtime shifts `lineno` from reporting the first decorator's line to reporting the `def`/`class` keyword line, the decorator lines silently fall out of the boundary set. Since the boundary map is used to determine where one statement ends and the next begins, missing entries create artificial gaps. The range-computation logic interprets these gaps as the preceding statement continuing further than it actually does, inflating its range into the next construct's prefix.

The cognitive trap is **version-stable assumption**: developers treat metadata fields as having fixed, well-understood semantics. When such fields subtly narrow their scope across versions, no error is raised — the field still returns a valid integer — so the degradation is invisible until users observe incorrect output on specific runtime versions.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Error messages or source excerpts display extra unrelated lines following the actual statement of interest
  - The problem is **version-dependent** — it only reproduces on newer runtime versions
  - Regression in edge cases involving decorated functions/classes immediately following the statement being analyzed
  - No explicit errors or exceptions; the output is subtly wrong rather than broken

### 解决步骤
1. **Locate the AST walker** that collects statement line numbers to build the boundary map (the set of "known statement start lines" used for range computation).
2. **Audit the walker's line-number extraction logic**: determine whether it relies solely on each node's primary `lineno` attribute, or whether it also accounts for auxiliary line-bearing sub-elements (decorators, annotations, modifiers) that carry their own distinct line numbers.
3. **Explicitly iterate over prefixed sub-elements**: for every node type that has sub-elements with independent line numbers (e.g., `decorator_list` on `FunctionDef`, `AsyncFunctionDef`, `ClassDef`), add their line numbers to the boundary set alongside the node's primary `lineno`.
4. **Enumerate all affected node types comprehensively**: don't fix only the observed case — systematically identify every AST node kind that can carry prefixed elements with independent line numbers and apply the same treatment.
5. **Add regression tests**: create test cases with decorated constructs immediately following the statement whose range is being computed, and verify the range terminates before the decorator line. Test across multiple runtime versions if possible.

### Why This Works

Explicitly collecting line numbers from sub-elements (decorators, annotations) restores the boundary entries that the primary `lineno` no longer provides after the upstream representation shift. This makes the boundary map **complete and version-invariant** — it no longer depends on the runtime's choice of which line to assign as the node's primary line number. The fix is robust because it derives boundary information from the full syntactic structure rather than from a single summary field whose semantics are outside the project's control.

## Boundary Cases

- **Multiple stacked decorators**: each decorator occupies its own line; all must be added to the boundary set, not just the first or last.
- **Async function definitions**: `AsyncFunctionDef` is a separate node type from `FunctionDef` and must be handled independently — it's easy to fix one and miss the other.
- **Class definitions with decorators**: the same pattern applies to `ClassDef` nodes, which also carry `decorator_list`.
- **Single-line decorated definitions**: when a decorator and the `def`/`class` keyword are on the same line (unusual but syntactically possible in some contexts), adding the decorator line should be a no-op since it matches the keyword line.
- **Runtime versions where the old behavior persists**: the fix must be safe on older runtimes where `lineno` still points to the first decorator — adding decorator lines redundantly to the set is harmless (idempotent set insertion).
- **Nested decorated definitions**: a decorated function inside another decorated function; both levels of decoration must contribute to the boundary map.

## PR Examples

- **pytest-dev__pytest-9359**: AST-based source boundary computation broke on Python versions where `lineno` for decorated definitions shifted from the first decorator line to the `def`/`class` keyword line, causing assertion error messages to include extra unrelated lines from subsequent decorators.