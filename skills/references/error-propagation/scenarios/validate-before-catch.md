## Problem Description

When a broad exception handler (e.g., `except AttributeError`, `except Exception`) is narrowed to catch only semantically meaningful exceptions (e.g., `ValueError`, `OverflowError`), previously silent failure paths become unhandled crashes. This occurs because the broad handler was incidentally catching exceptions produced by intermediate operations on invalid inputs — such as calling `.group()` on a `None` regex match result — rather than catching explicitly raised validation errors. The narrowing is a correctness improvement, but it exposes the absence of explicit input validation that was previously masked by the overly broad catch.

## Root Cause Analysis

Broad exception handlers create invisible coupling between error-handling intent and incidental implementation details. When code inside a `try` block processes input through multiple steps, some steps may return sentinel values (like `None`) on malformed input. Subsequent operations on those sentinels produce incidental exceptions (e.g., `AttributeError` from attribute access on `None`) that happen to be caught by the broad handler. This accidental error path functions as a de facto validation mechanism — but it is never documented, never tested, and entirely dependent on implementation details.

When a developer correctly narrows the exception handler to catch only the exceptions that are *intentionally* raised (like `ValueError`), the incidental exception types (like `AttributeError`) fall outside the new catch clause. The result is an unhandled exception on edge-case inputs (empty strings, `None`, zero-length collections, etc.) that were previously silently absorbed.

The cognitive trap is that developers audit the `try` block, see explicit `raise ValueError(...)` statements, and conclude all failure modes are covered — not realizing that some failure modes were handled by incidental exceptions from unrelated operations that the broad handler happened to catch.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - A recent commit narrowed an exception handler from a broad type (e.g., `AttributeError`, `Exception`) to a specific type (e.g., `ValueError`, `OverflowError`).
  - Edge-case inputs (empty strings, `None`, malformed formats) that previously returned a default value or were silently ignored now produce unhandled exceptions (crashes).
  - The crash traceback shows an `AttributeError`, `TypeError`, or similar exception originating from an intermediate operation inside the `try` block — not from an explicit `raise` statement.
  - The failure is a regression: the same input worked before the handler was narrowed.

### 解决步骤
1. **Audit every expression inside the `try` block** to identify which ones could raise exceptions that were previously caught by the broader handler but are NOT caught by the narrower one. Pay special attention to chained operations like `regex.match(input).group(1)` where the intermediate result can be `None`.
2. **Trace degenerate inputs through the code path.** For each intermediate function call, determine what it returns on edge-case inputs (empty string, `None`, zero-length collection, unexpected type). Then determine what exception the *next* operation on that result would raise.
3. **Add explicit validation checks** at each point where an intermediate result could be `None` or otherwise invalid. When validation fails, raise the canonical exception type that the narrowed handler expects (e.g., `raise ValueError(...)`) rather than relying on incidental downstream failures.
4. **Confirm the narrowed handler is now sufficient.** Verify that every reachable exception inside the `try` block is either (a) explicitly raised with the expected type, or (b) represents a genuine unexpected error that should propagate. Remove any remaining broad exception types from the catch clause.
5. **Write test cases for the degenerate inputs** that were previously silently handled by the broad catch. These tests encode the contract that edge-case inputs produce the expected default/error behavior rather than crashes.

### Why This Works

Making validation explicit at the point of failure ensures that the exception handler's catch list precisely documents which error conditions are expected. The `try/except` block becomes a contract: the `try` body explicitly raises known exception types for known failure modes, and the `except` clause catches exactly those types. This eliminates the invisible coupling between incidental implementation details (like `None` return values producing `AttributeError`) and error-handling intent. The code becomes resilient to future refactoring of either the handler or the try-block internals, because validation is an explicit design choice rather than an accidental side effect.

## Boundary Cases
- **Empty strings** passed to parsing/validation functions where a regex match returns `None`, and subsequent `.group()` calls raise `AttributeError`.
- **`None` values** propagated through chains of method calls where the first failure produces a sentinel that causes an unrelated exception type downstream.
- **Zero-length or whitespace-only inputs** that pass initial type checks but fail intermediate parsing steps silently.
- **Multiple independent validation steps** within a single `try` block, where only some steps have explicit `raise` statements and others rely on incidental failures.
- **Nested function calls** where the incidental exception originates several frames deep, making it non-obvious during code review that the broad handler was catching it.

## PR Examples
- django__django-15498