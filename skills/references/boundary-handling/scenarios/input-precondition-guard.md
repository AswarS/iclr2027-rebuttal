## Problem Description

A data formatting or transformation utility function receives input from a data layer (e.g., database fields, model attributes) that can legitimately be null, None, or empty. The function immediately performs content-dependent operations—such as indexing the first character, slicing, regex matching, or type-specific method calls—without first verifying that the input is non-null and non-empty. This results in low-level exceptions (e.g., `IndexError`, `TypeError`, `AttributeError`) bubbling up through the call stack, crashing the application at the presentation layer.

The core pattern is an **implicit assumption violation**: the utility function was written under the assumption that it would only ever receive well-formed, pre-validated input, but the actual call chain passes raw data-layer values through without intermediate coercion or validation. Nullable database fields, optional model attributes, and newly added display configurations all create pathways for degenerate values to reach the function unguarded.

## Root Cause Analysis

The underlying principle is a **trust boundary mismatch**. The utility function treats itself as operating in a closed, trusted context where all inputs are guaranteed valid. However, it actually sits at a boundary between the data layer (which can produce the full range of values including null/empty) and the presentation layer (which expects graceful handling of all inputs).

This cognitive trap—"someone upstream already handled this"—is the root cause. In practice, data pipelines have gaps where null values flow through without coercion. This is especially common when:

- Optional/nullable fields are added to a model after the utility was written.
- Display configurations change to include fields that were previously excluded.
- The utility is reused in new contexts where the upstream validation guarantees no longer hold.

The function's first operation on the input (e.g., `value[0]`, `value.split()`) becomes the crash site, but the real defect is the absence of a precondition guard that accounts for the data layer's full value domain.

## Solution Strategy

### 识别信号
- 观测到的现象: `IndexError`, `TypeError`, `AttributeError`, or similar low-level exception originating from a string/sequence operation (indexing, slicing, pattern matching) on the first character or element of an input value.
- The traceback points to an internal formatting or transformation utility, not to user-facing input handling code.
- The triggering input is a null, None, or empty value that originated from a database field or model attribute.

### 解决步骤
1. **Trace the full input domain**: Identify all entry points to the formatting/transformation function and trace what values the data layer can produce—specifically whether null (`None`), empty string (`""`), or other degenerate values are possible for each call site.
2. **Add an early-return guard clause**: At the very top of the function body, before any content-dependent operations, insert a check for null and empty inputs. This guard must be the first logic in the function so the precondition is immediately visible and no code path can bypass it.
3. **Return the degenerate input as-is**: When the guard triggers, return the original degenerate value (or wrap it in the function's standard output type) rather than substituting a synthetic default like `0`, `"0"`, or a placeholder. This preserves the semantic meaning of "no data" for the caller and avoids misrepresenting absent data as meaningful data—a silent correctness bug worse than the original crash.
4. **Verify downstream handling**: Confirm that callers handle the pass-through of null/empty gracefully (e.g., the display layer renders blank for null fields, templates use default filters, serializers omit the field).
5. **Add regression tests**: Write test cases that exercise the function with `None`, `""`, and any other degenerate values the data layer can produce, asserting that no exception is raised and the output is semantically correct.

### Why This Works

Utility functions that sit between a data layer and a presentation layer must defensively handle the **full range of values** the data layer can produce, not just the "happy path" of well-formed data. By placing the guard at the very top of the function, we establish a clear, visible contract: this function tolerates degenerate input and handles it gracefully. Returning the original degenerate value rather than a synthetic default maintains data integrity—absent data remains absent rather than being silently converted into misleading non-null values.

## Boundary Cases
- **`None` input**: The most common degenerate value from nullable database fields. Must not trigger any attribute access or method call.
- **Empty string `""`**: A valid but contentless value that will cause `IndexError` on `value[0]` or unexpected behavior in regex matching.
- **Whitespace-only strings**: Depending on the function's semantics, these may need to be treated as empty or as valid input—clarify the contract.
- **Non-string types passed unexpectedly**: If the data layer can produce integers, floats, or other types for the field, the guard should account for type mismatches or the function should document its type expectations.
- **Chained utility calls**: If the function's output feeds into another utility with similar assumptions, the downstream function also needs its own guard—don't rely on a single guard propagating safety through the chain.

## PR Examples
- django__django-16046