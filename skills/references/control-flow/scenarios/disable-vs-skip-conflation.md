## Problem Description

When a configuration flag is introduced to "disable" or "skip" a step in a multi-stage pipeline, developers often implement it as bypassing the entire step — including the postconditions that downstream stages implicitly depend on. This conflation of "skip the method" with "skip the goal" causes crashes, undefined-resource errors, or inconsistent state in subsequent pipeline stages that assume certain artifacts (database tables, files, initialized state) were created by the skipped step.

This pattern is especially prevalent when disable flags are retrofitted onto pipelines originally designed as a single linear path, where inter-step postconditions were never explicitly documented or enforced.

## Root Cause Analysis

The fundamental issue is a **conflation between a method and its goal**. Every step in a pipeline serves a purpose — it produces some postcondition (e.g., "database schema exists," "cache is warm," "configuration is validated"). When a flag is added to disable that step, the implementation typically takes the form:

```
if not disabled:
    run_step()
# else: do nothing
```

The `do nothing` branch silently violates the postcondition contract. Downstream code was written under the assumption that the postcondition is **always** satisfied — it was never an explicit contract, just an implicit invariant of the original single-path design. The disable flag breaks this invariant without providing an alternative path to satisfy it.

The cognitive trap is that the developer focuses on what they want to *remove* (the method) without auditing what the method *provides* to the rest of the system. The flag's semantics are "don't use method X," but the implementation's semantics become "abandon the goal that X was achieving."

## Solution Strategy

### 识别信号
- 观测到的现象: A crash, exception, or undefined-resource error occurs in a step that runs **after** a conditionally-disabled step. The error references artifacts (tables, files, state objects) that the disabled step would have created. The failure only manifests when the disable flag is active — the pipeline works fine with the flag off.

### 解决步骤
1. **Map postconditions**: Identify what downstream operations depend on as outputs of the disabled step. Ask: "What state does the system expect to exist after this step completes, regardless of how it was created?"
2. **Separate goal from method**: Clearly distinguish the *goal* (e.g., "database schema must exist") from the *method* (e.g., "run migration files"). The disable flag should only suppress the method, not the goal.
3. **Implement an alternative path**: When the flag is set, replace the disabled method with an alternative mechanism that still achieves the required postcondition. For example, if migrations are skipped, use a direct schema-creation path (e.g., `syncdb` or `CreateModel`) instead.
4. **Guard configuration with try/finally**: If the alternative path requires temporarily overriding configuration (e.g., re-enabling a subsystem the flag disabled), use a `try/finally` pattern to ensure the original configuration is restored after the alternative completes, preventing side effects on subsequent operations.
5. **Validate postcondition compatibility**: Verify that the alternative path leaves the system in a state fully compatible with all subsequent stages (serialization, data loading, teardown, etc.). Run the full pipeline with the flag both on and off to confirm behavioral equivalence where it matters.

### Why This Works

The solution preserves the **postcondition invariant** that downstream code relies on, while still honoring the user's intent to disable a specific mechanism. By replacing the method rather than eliminating the goal, the pipeline's implicit contracts remain intact. The try/finally guard ensures that the temporary workaround doesn't leak configuration changes into unrelated parts of the system, maintaining isolation between the "skip" semantics and the rest of the pipeline.

## Boundary Cases

- **The alternative path has different side effects**: Direct schema creation may not record migration history, causing future migration runs to attempt re-applying migrations. Ensure the alternative path also satisfies secondary postconditions (e.g., marking migrations as applied).
- **Nested or recursive disable flags**: If the alternative path itself consults the same disable flag (e.g., a direct creation path that internally checks "should I skip migrations?"), infinite loops or re-suppression can occur. The try/finally override must be scoped precisely.
- **Multiple downstream dependents with different expectations**: Different subsequent stages may depend on subtly different aspects of the postcondition. The alternative path must satisfy the union of all downstream expectations, not just the most obvious one.
- **Flag interactions**: When multiple disable flags exist (e.g., "skip migrations" + "skip data loading"), the combination may create novel postcondition gaps that neither flag's alternative path addresses individually.
- **Third-party or plugin code**: External code may also depend on the postcondition. The alternative path must be compatible with extension points that the original method triggered (signals, hooks, callbacks).

## PR Examples

- **django__django-13448**: A "skip migrations" flag in Django's test runner bypassed migration execution entirely, but downstream test database setup still expected the schema to exist. The fix replaced the skipped migration path with direct table creation (`syncdb`-style), preserving the "schema exists" postcondition while honoring the "don't run migration files" intent.