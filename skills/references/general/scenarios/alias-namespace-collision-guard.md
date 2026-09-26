## Problem Description

When constructing SQL queries that combine `.values()`, `.annotate()`, and JOINs across related models, annotation aliases can collide with concrete column names on joined tables. This causes the database's GROUP BY clause to contain ambiguous references — the database engine cannot determine whether a bare name refers to the annotation alias or a real column from a joined table. This manifests as a "column reference is ambiguous" error, particularly on PostgreSQL, and represents a leaky abstraction where the ORM's internal namespace assumptions break down at the SQL level.

## Root Cause Analysis

The GROUP BY construction logic implicitly assumes that annotation aliases occupy an isolated namespace and can safely be referenced by their bare names. However, SQL's name resolution in GROUP BY considers column names from **all** tables in the FROM/JOIN clauses simultaneously. When an annotation alias (e.g., `"value"`) happens to match a concrete column name on any joined table, the database cannot disambiguate the GROUP BY reference. The ORM's abstraction leaks because it treats annotation aliases as unique identifiers without accounting for the broader SQL namespace that includes every column from every joined table. This is an edge case that only surfaces when specific naming collisions occur across model boundaries.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `ProgrammingError: column reference "X" is ambiguous` at query execution time (especially on PostgreSQL)
  - The error occurs specifically on queries combining `.values()`, `.annotate()`, and foreign key traversals (JOINs)
  - The annotation alias exactly matches a concrete database column name on one of the joined tables
  - The query works fine when the annotation is renamed to a non-colliding alias

### 解决步骤
1. **Identify all concrete column names** from every table referenced in the query — including the base table and all tables introduced via JOINs.
2. **Check for namespace collisions** before adding annotation references to the GROUP BY clause: compare each annotation alias against the collected set of concrete column names from joined tables.
3. **Substitute the full source expression** for any annotation whose alias collides with a concrete column name. Instead of emitting a bare symbolic reference (which resolves to the ambiguous alias), emit the annotation's underlying computed expression, which is structurally distinct and unambiguous.
4. **Preserve the existing behavior** for non-colliding annotations, keeping the optimized reference-based approach where it is safe.
5. **Add regression tests** that specifically combine annotations with aliases matching column names on joined tables, exercising GROUP BY operations to prevent future regressions.

### Why This Works

A full source expression (e.g., `SUM("table"."column")`) is structurally distinct from a simple column reference and cannot be confused with a column from a joined table. By detecting collisions at query-construction time — before the SQL compiler renders the GROUP BY — the fix resolves ambiguity at the appropriate abstraction layer. The compiler faithfully outputs whatever references it receives, so the collision must be resolved upstream. This approach is minimally invasive: it only changes behavior for the specific edge case where a collision exists, preserving the existing optimized path for the common case.

## Boundary Cases

- **Multiple JOINs with overlapping column names**: The collision check must scan columns from *all* joined tables, not just the immediately related one, since SQL considers the full FROM/JOIN scope.
- **Self-referential JOINs**: When a model joins to itself, every column name on that model is duplicated; annotations matching any of those column names must use full expressions.
- **Subquery annotations**: Annotations backed by subqueries may have aliases that collide with outer table columns; the same collision-detection logic must apply.
- **Database-specific behavior**: Some databases (e.g., SQLite, MySQL) may resolve ambiguity differently or not raise errors, but the fix should be applied universally to ensure portable, correct SQL.
- **Chained `.values().annotate().values()`**: Re-annotation or re-selection chains may re-introduce collisions at different stages of query construction; each GROUP BY construction pass must re-check.
- **No JOINs present**: When the query involves only a single table, annotation aliases cannot collide with columns from other tables, so the optimization of using bare references remains safe.

## PR Examples

- django__django-12589