## Problem Description

Reversible operations (such as schema migration renames, resource moves, or re-keying operations) can crash or produce incorrect behavior when applied in a round-trip sequence (forward → backward → forward). The core issue is that the forward operation assumes its precondition — that the source identifier differs from the target identifier — always holds. However, after a backward pass restores state, the resolved source name may coincidentally equal the target name, especially when identifiers are auto-generated or lazily resolved. The forward operation then attempts a mutation (e.g., `ALTER TABLE RENAME`) where source and target are identical, causing a database error, framework crash, or silent corruption.

This pattern is a specific instance of **symmetry-breaking in reversible state machines**: the forward and backward paths do not form a perfectly symmetric pair because name resolution logic introduces hidden state dependencies that break the assumed invariant.

## Root Cause Analysis

The underlying principle is an **implicit assumption violation** in the operation's precondition. Developers design the forward operation reasoning only about the canonical "fresh" application path, where the source name is guaranteed to differ from the target. They forget that:

1. **Reversibility creates additional state transitions.** A migration framework allows arbitrary sequences of `apply` and `unapply`, meaning the forward operation can be invoked from states that were never part of the original design intent.

2. **Auto-generated or dynamically resolved identifiers are non-deterministic across paths.** When the "old" name is computed lazily (e.g., auto-generated index names, default table names derived from model metadata), the backward pass may restore state where the resolved old name happens to coincide with the forward target name.

3. **Idempotency is not optional for reversible operations.** If the desired postcondition already holds, the operation must be a no-op. Issuing a redundant mutation command (like renaming X to X) is not guaranteed to be harmless — many backends treat it as an error.

The cognitive trap is treating the forward operation as a one-shot transformation rather than as a **convergent state transition** that must gracefully handle already-satisfied postconditions.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Crash or exception** when running a migration sequence that includes backward then forward application (e.g., `migrate 0003` → `migrate 0002` → `migrate 0003`).
  - **Regression on edge cases** where auto-generated names (default index names, implicit table names) are involved in rename or move operations.
  - Error messages indicating an attempt to rename/move a resource to its own current name (e.g., `relation "X" already exists` or `Cannot rename "X" to "X"`).
  - The bug only manifests on round-trip; single forward application works fine.

### 解决步骤
1. **Inventory all reversible operations that mutate named resources.** Identify every operation in the codebase that performs renames, moves, re-keys, or any mutation where a source identifier is transformed into a target identifier — and that also defines a reverse operation.

2. **Trace the full name resolution path.** For each such operation, map out how the source ("old") identifier is resolved. Pay special attention to auto-generated names, lazy resolution, or names derived from other model/schema metadata that may change between forward and backward passes.

3. **Insert an idempotency guard after resolution but before mutation.** After all name resolution logic has executed and the final concrete source and target identifiers are known, add a comparison:
   ```
   if resolved_source == resolved_target:
       return  # no-op — postcondition already satisfied
   ```
   This guard must be placed **after** all dynamic name computation and **before** the actual state-altering call (e.g., the SQL `ALTER` statement or API call).

4. **Verify the guard does not mask real errors.** Ensure that the no-op path is truly correct — that the postcondition (target state) genuinely holds when source equals target. Log or emit a debug-level message if desired for observability.

5. **Add round-trip regression tests.** Write a test that exercises the full cycle: forward → backward → forward. Verify that no exception is raised and that the final state matches the expected postcondition. Include variants with auto-generated names and explicitly specified names.

### Why This Works

The idempotency guard transforms the operation from an **imperative command** ("rename X to Y") into a **declarative convergence** ("ensure the name is Y"). This is the correct semantic for any operation embedded in a reversible state machine, because the framework makes no guarantees about the starting state — only that the operation should produce the correct ending state. By checking the postcondition before acting, the operation becomes safe to invoke from any reachable state, including states produced by backward application.

## Boundary Cases

- **Auto-generated names that differ across database backends.** The idempotency guard must use the fully backend-resolved name, not a generic or truncated version. A name that matches on PostgreSQL might not match on MySQL due to length truncation rules.
- **Case sensitivity in identifiers.** Some databases are case-insensitive for identifiers. The comparison in the guard should use the same normalization the backend uses (e.g., lowercasing) to avoid false negatives.
- **Composite renames (e.g., renaming both a table and a column in one operation).** The guard must check all components — a partial match (table name matches but column name doesn't) should not trigger the no-op path.
- **Operations where source-equals-target is genuinely an error in forward-only context.** If the operation should never be authored with identical source and target, consider emitting a warning while still handling the round-trip case gracefully. Distinguish between "user authored a no-op migration" and "round-trip produced a coincidental match."
- **Chained reversible operations where intermediate state matters.** If operation B depends on operation A's side effects, ensure that A's no-op path doesn't silently skip state that B requires. The guard should only suppress the external mutation, not internal bookkeeping.

## PR Examples

- **django__django-15695**: A schema migration `RenameIndex` operation crashed when applied forward after a backward pass, because the auto-generated old index name resolved to the same value as the new index name. The fix added an idempotency check comparing the resolved old and new names before issuing the `ALTER INDEX RENAME` statement.