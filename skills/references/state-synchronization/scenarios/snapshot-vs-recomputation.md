## Problem Description

When a system uses **snapshots** of initial state for later comparison (e.g., change detection), but the snapshot is **recomputed from a factory/callable** instead of being preserved from the original capture, the baseline drifts across render or evaluation cycles. This causes silent data loss, incorrect change detection, or inconsistent state — particularly when the system re-evaluates after a failed intermediate step (such as form validation failure) and the callable default produces a fresh, empty value that overwrites or misrepresents the user's original input.

This pattern manifests anywhere a point-in-time snapshot is needed for comparison, but the implementation implicitly assumes the snapshot source is idempotent and stateless, when in reality it is a factory that produces distinct instances on each invocation.

## Root Cause Analysis

The fundamental issue is a **conflation of "current default" with "original snapshot."** Systems that perform change detection rely on comparing a current value against a stable baseline. When that baseline is derived from a callable (e.g., `list`, `dict`, a factory function, or any non-constant initializer), each invocation yields a new, independent object. If the system regenerates the baseline on every cycle instead of persisting the one originally presented to the user, the comparison anchor shifts silently.

The cognitive trap is the assumption that initial/default values are **pure constants** that can be safely recomputed at any time. This holds for scalar literals but breaks for callable defaults, mutable containers, or any source that produces fresh instances. The moment a snapshot is taken for comparison purposes, it must be **frozen and preserved** — not regenerated — or the entire comparison mechanism becomes unreliable.

In the specific case of form re-rendering after validation failure: the hidden widget that stores the initial value re-invokes the callable default, producing a fresh empty value. On the next submission, the system compares the user's input against this fresh empty value instead of the original snapshot, leading to either false "no change" conclusions or silent loss of the submitted data.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Silent data loss**: Submitting a form with errors a second time causes fields with callable defaults to lose their previously submitted values.
  - **Inconsistent change detection**: The system incorrectly reports "no change" because the recomputed baseline now matches the recomputed default rather than the user's original input.
  - **Intermittent correctness**: The first submission works correctly, but subsequent re-renders after validation failure produce wrong results — a hallmark of state desynchronization across cycles.

### 解决步骤
1. **Audit all rendering/evaluation paths** where a hidden or internal snapshot value is populated. Identify any path that computes the snapshot by invoking a callable default or factory rather than reading from previously persisted state.
2. **Distinguish bound vs. unbound contexts**: When the system is in a "bound" state (i.e., it has already received and is processing submitted data), check whether the submitted data already contains a value for the snapshot field.
3. **Prefer persisted snapshot over recomputation**: If a previously submitted snapshot value exists in the bound data, extract it using the appropriate deserialization/extraction method and use that value as the baseline. Do not re-invoke the callable default.
4. **Fall back to computation only on first render**: Only compute the initial value from the field's default or callable when the system is in an unbound state (first render) or when no prior snapshot data exists.
5. **Validate the fix end-to-end**: (a) Trigger a validation failure on a field with a callable default, (b) re-submit without changes, (c) confirm the hidden snapshot value is preserved identically across both submissions, and (d) verify change detection correctly identifies whether the user actually modified the field.

### Why This Works

A snapshot's purpose is to serve as a **stable reference point** for comparison. By preserving the originally captured value from submitted data rather than regenerating it, the baseline remains anchored to the exact state the user originally saw. This eliminates drift caused by callable defaults producing fresh instances and restores the correctness of any downstream comparison logic. The principle is simple: **capture once, reuse always** — never regenerate a snapshot that was meant to be immutable.

## Boundary Cases
- **Callable defaults that are truly idempotent** (e.g., always return the same singleton): The fix is still correct — preserving the submitted value is a no-op in terms of outcome but avoids relying on an implicit idempotency guarantee.
- **Fields where the initial value changes between renders legitimately** (e.g., a timestamp "now"): These fields should not use hidden-initial-based change detection at all, or must explicitly opt out of snapshot preservation.
- **Nested or composite callable defaults** (e.g., a factory returning nested mutable structures): Serialization/deserialization of the snapshot must handle deep equality correctly; shallow comparison may still produce false positives.
- **Multiple validation failure cycles**: The snapshot must remain stable across arbitrarily many re-render cycles, not just one — the fix must read from the most recent submission's snapshot data, which itself was preserved from the original.

## PR Examples
- django__django-16229