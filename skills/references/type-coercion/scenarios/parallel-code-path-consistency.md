## Problem Description

When a library provides multiple code paths (e.g., buffered vs. streaming) that promise equivalent output transformations on the same underlying data, inconsistencies in their fallback strategies can cause silent type contract violations. Specifically, one path may gracefully handle missing configuration (e.g., auto-detecting character encoding when none is declared in HTTP headers), while a parallel path silently skips the transformation entirely — returning raw, untransformed data (bytes instead of strings) without raising any error. The caller, who chose the streaming path for performance or memory reasons rather than for different correctness semantics, receives data of an unexpected type with no indication that anything went wrong.

## Root Cause Analysis

The root cause is **asymmetric fallback logic across parallel code paths that share the same behavioral contract**. This arises from a cognitive conflation: treating "no explicit configuration declared in metadata" as equivalent to "no valid configuration exists." When the buffered path already solves the inference problem (e.g., using heuristic encoding detection like `chardet` when no charset is present in HTTP `Content-Type` headers), the streaming path's failure to reuse that same inference mechanism is a symmetry-breaking defect. The absence of an explicit declaration is an input condition that both paths must handle identically — it is not a signal to silently degrade behavior.

This pattern is especially insidious because:
- The defect is **data-dependent**: it only manifests when metadata happens to be absent, meaning it passes tests where metadata is present.
- The failure is **silent**: no exception is raised; the return type simply changes from `str` to `bytes`.
- The downstream impact is **displaced**: type errors or data corruption surface far from the actual source of the problem, making debugging extremely difficult.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Silent data loss / wrong output**: The streaming path returns raw bytes when decoded strings were expected, but no error is raised.
  - **Type error downstream**: Code consuming the streaming output fails with `TypeError` or produces garbled results because it expected `str` but received `bytes`.
  - **Inconsistency between paths**: Calling the buffered API (e.g., `.text`) returns correctly decoded text, while the streaming API (e.g., `iter_content(decode_unicode=True)`) returns raw bytes for the same response — but only when the response lacks explicit encoding metadata.

### 解决步骤
1. **Map all public API surfaces that promise the same output contract.** Enumerate every method, property, or iterator that claims to return transformed data (e.g., decoded text). For each, trace the full fallback chain used when explicit configuration (e.g., charset from headers) is missing.

2. **Compare fallback strategies across parallel paths.** Specifically check whether the streaming/incremental path mirrors the buffered/complete path's fallback logic. Look for branches where one path invokes heuristic detection (e.g., `chardet`-based apparent encoding) while the other returns `None` or skips the transformation when the explicit value is absent.

3. **Unify the fallback chain.** When explicit configuration is absent, apply the same heuristic detection fallback in the streaming path that the buffered path already uses. Reference the identical detection mechanism (e.g., the same `apparent_encoding` property or shared utility function) to prevent future divergence. Avoid duplicating logic — extract a shared helper if one does not already exist.

4. **Add explicit error handling for unresolvable fallback.** If both the explicit configuration and the heuristic detection fail to produce a valid transformation parameter (e.g., `chardet` returns `None` or an invalid codec name), raise a clear, descriptive error rather than silently returning untransformed data. Catch specific exceptions (`LookupError` for invalid codec names, `TypeError` for null values passed to codec lookup) and wrap them in a domain-appropriate error with an actionable message.

5. **Add tests that exercise the streaming path with missing metadata.** Create test cases where the response lacks explicit encoding metadata (e.g., no `charset` in `Content-Type`) and verify that:
   - The streaming path returns the same **type** (`str`, not `bytes`) as the buffered path.
   - The streaming path returns **equivalent content** to the buffered path.
   - When all fallbacks fail, a clear error is raised rather than silent degradation.

### Why This Works

When two API surfaces promise the same behavioral contract, a caller's choice between them is a **performance/memory tradeoff**, not an opt-in to different correctness semantics. Unifying the fallback chain enforces this invariant structurally. By extracting or reusing a shared detection mechanism, future changes to the fallback logic automatically propagate to all paths, preventing re-introduction of the asymmetry. Explicit error handling on total fallback failure converts a silent, displaced bug into an immediate, locatable one — strictly better for debuggability and correctness.

## Boundary Cases
- **Heuristic detection returns a valid but incorrect encoding**: The streaming path should still behave identically to the buffered path (both will decode with the same wrong encoding), preserving behavioral symmetry even when the heuristic is imperfect.
- **Heuristic detection returns `None` or an unrecognizable codec name**: Both paths must raise a clear error rather than one silently returning bytes and the other raising an opaque `LookupError`.
- **Empty response body**: Encoding detection on zero-length content may behave unpredictably; ensure both paths handle this gracefully (e.g., yield/return an empty string, not empty bytes).
- **Metadata is present but specifies an invalid or unsupported encoding**: Both paths should fail identically — either falling back to heuristic detection or raising the same error.
- **Mixed usage**: A caller who accesses both the buffered property and the streaming iterator on the same response object should observe consistent encoding decisions, even if the detection is invoked lazily.

## PR Examples
- **psf__requests-3362**: The `iter_content(decode_unicode=True)` streaming path in the `requests` library failed to apply heuristic encoding detection (`apparent_encoding`) when no charset was declared in the HTTP response headers, while the `.text` buffered property correctly fell back to `chardet`-based detection. This caused the iterator to silently yield raw `bytes` instead of decoded `str` chunks.