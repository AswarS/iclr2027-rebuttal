## Problem Description

When a data migration performs bulk reassignment of records from one foreign key target to another (e.g., re-parenting rows from category A to category B), it implicitly assumes a clean partition of data — that records exist only under the source key and never under the destination key. In real-world systems that have undergone schema evolution (entity deletion, recreation, renaming, manual database edits, or non-linear upgrade paths), overlapping records may already exist at both the source and destination. If the target table has a uniqueness constraint spanning the foreign key column and other columns, a naive bulk UPDATE will violate that constraint and crash the entire migration, potentially leaving the database in a partially migrated, broken state.

## Root Cause Analysis

The fundamental issue is **implicit assumption violation** combined with **invariant erosion** over time. Migration authors reason about data transformations as if every database instance reached the current state through an identical, pristine sequence of migrations. In practice, databases accumulate state from prior software versions, manual interventions, hotfixes, partial rollbacks, and non-linear upgrade paths. This means the precondition "no records exist at the destination foreign key" — which the migration silently depends on — can be false.

The deeper principle is that **idempotency and defensive error handling are not optional in data migrations**. Unlike schema migrations (which are largely declarative and can be checked structurally), data migrations encode assumptions about runtime state that may not hold. A bulk UPDATE that works perfectly on a freshly seeded database can crash catastrophically on a production database with years of accumulated state drift.

Additionally, database transaction semantics compound the problem: on backends like PostgreSQL, any unhandled error inside a transaction aborts the entire transaction, making it impossible to skip one failing record and continue — unless savepoints are used explicitly.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `IntegrityError` or `UniqueViolation` during a data migration that bulk-updates a foreign key column
  - Migration crashes on production but passes on fresh/test databases
  - The target table has a composite uniqueness constraint involving the column being updated
  - The system has undergone entity deletion and recreation, or has databases with divergent migration histories

### 解决步骤
1. **Identify the uniqueness constraint** on the target table that spans the column being updated and any other columns. Confirm that a bulk UPDATE could produce duplicate composite key values if matching rows already exist at the destination.

2. **Replace the bulk UPDATE with per-record (or per-logical-group) iteration.** This ensures that a constraint violation on one record does not block processing of all other records.

3. **Wrap each individual reassignment in a savepoint** (e.g., `transaction.atomic()` as a nested context manager in Django). This is critical because databases like PostgreSQL abort the entire transaction on any unhandled error — a savepoint allows rolling back only the failed sub-operation.

4. **Catch the specific integrity/constraint violation error** within the savepoint scope. When caught:
   - Do **not** silently swallow it.
   - Emit a descriptive warning (e.g., via `warnings.warn()` or logging) that explains duplicate records were found and manual auditing may be needed.
   - Allow the migration to continue processing remaining records.

5. **Optionally, add a pre-check query** that identifies source records whose destination already has a matching row under the uniqueness constraint. These can be skipped or merged explicitly, reducing reliance on exception-driven control flow and providing clearer audit output.

### Why This Works

- **Savepoints** isolate failures to individual operations, preventing one bad record from aborting the entire migration transaction. This aligns the migration's error handling with the database's transactional semantics.
- **Per-record iteration** transforms an all-or-nothing operation into a gracefully degrading one, where the vast majority of records migrate successfully even if a few conflict.
- **Warnings instead of crashes or silent swallowing** balance forward progress (the migration completes, the system is usable) with operational awareness (administrators know to audit for data inconsistencies).
- **Pre-check queries** make the migration's assumptions explicit and testable, converting an implicit precondition into a verified one.

The overall principle is that **data migrations must be defensive against state they did not create** — they should be as close to idempotent as possible, handling pre-existing destination state gracefully rather than assuming it away.

## Boundary Cases
- **All source records already have matching destination records**: The migration should complete successfully (as a no-op for those records) with appropriate warnings, not crash entirely.
- **Mixed state where some records conflict and others don't**: The non-conflicting records must still be migrated; only the conflicting ones should be skipped/warned.
- **Database backends with different transaction error semantics**: On SQLite, errors don't necessarily abort the transaction, so the migration might appear to work without savepoints — but this masks the bug that will surface on PostgreSQL or other stricter backends. Savepoints should be used unconditionally for portability.
- **Re-running the migration after a partial failure**: If the migration is re-run (e.g., after a fix or in a `--fake` recovery scenario), it should not fail on records that were already successfully migrated in a prior run — reinforcing the need for idempotent per-record logic.
- **Large tables with millions of rows**: Per-record iteration with savepoints has performance implications. Consider batching with pre-check queries to minimize the number of savepoint operations while still handling conflicts gracefully.

## PR Examples
- django__django-11283