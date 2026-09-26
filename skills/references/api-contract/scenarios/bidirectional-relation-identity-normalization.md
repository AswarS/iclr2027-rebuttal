## Problem Description

When a system supports bidirectional relationships (e.g., forward foreign key and reverse relation), internal data structures keyed by field objects can silently break due to identity mismatch between forward and reverse field representations. The same logical database relationship, when traversed in opposite directions, resolves to different object types (e.g., a forward `ForeignKey` field vs. a reverse relation descriptor). If a dictionary or map is built using one representation as the key but consumers perform lookups using the other, the lookup fails silently, causing fallback to default behavior — such as selecting all columns instead of only the requested subset.

This is a symmetry-breaking problem: the developer's mental model treats field resolution as returning a canonical object regardless of traversal direction, but the underlying implementation produces direction-dependent object identities that are not interchangeable as dictionary keys.

## Root Cause Analysis

Bidirectional relationships inherently have two object representations for a single underlying database constraint. Field resolution APIs return whichever representation matches the traversal direction — forward lookups yield the actual field object (e.g., `ForeignKey`), while reverse lookups yield a wrapper/descriptor object (e.g., `ForeignObjectRel`, `ManyToOneRel`). These two objects are **not identity-equal** (`is`) nor typically **equality-equal** (`==`) to each other.

When a field-limiting mechanism (like a select mask or deferred field set) constructs a dictionary keyed by resolved field objects from user-specified paths, and those paths traverse a reverse relation, the resulting keys are reverse descriptors. However, downstream query construction code looks up fields using forward field objects. The mismatch means the mask entry is never found, and the system silently falls back to its default (e.g., `SELECT *`), producing correct but suboptimal or unexpected output — a regression that manifests only on reverse-traversal edge cases.

The implicit assumption violated is: **"field name resolution always produces the same object type that downstream consumers use as lookup keys."**

## Solution Strategy

### 识别信号
- 观测到的现象: Field-limiting queries (e.g., `only()`, `defer()`, or equivalent column-selection APIs) work correctly for forward relations but silently include all columns when traversing reverse relations — a **wrong-output** / **regression-on-edge-case** failure
- Generated SQL shows `SELECT *` on a related table instead of the expected subset of columns
- The issue only manifests with reverse one-to-one or reverse foreign key traversals, not forward traversals

### 解决步骤
1. **Locate the mask/map construction point**: Find where the field select mask (or equivalent dictionary keyed by field objects) is built from user-specified field paths. This is typically a function that iterates over field names, resolves them via the model's meta field lookup, and inserts them into a dictionary.
2. **Detect reverse relation objects**: At the insertion point, check whether the resolved field object is a reverse relation descriptor rather than a forward field. Reverse relations typically wrap the actual forward field and expose it via an attribute (e.g., `related.field` or `.field` on the reverse descriptor).
3. **Normalize to forward field identity**: Before using the resolved object as a dictionary key, normalize reverse relation objects to their underlying forward field representation. This ensures a single canonical key identity regardless of traversal direction.
4. **Apply normalization at the earliest divergence point**: Keep the fix localized to the mask-building function rather than modifying multiple downstream consumers or the field resolution infrastructure itself.
5. **Validate with targeted tests**: Confirm that field-limiting queries through reverse one-to-one and reverse foreign key relations produce SQL containing only the specified columns, matching the behavior of equivalent forward-traversal queries.

### Why This Works

By normalizing reverse relation descriptors to their underlying forward field objects at the point of dictionary key insertion, we guarantee that all downstream lookups — which universally use forward field objects — will find the correct mask entries. This eliminates the identity mismatch without requiring changes to the broader field resolution system or to every consumer of the mask dictionary. The fix respects the principle of **canonical representation**: when multiple objects represent the same logical entity, choose one canonical form and normalize to it at the boundary where the ambiguity is introduced.

## Boundary Cases
- **Reverse one-to-one relations**: The most common trigger, since one-to-one reverse lookups are frequently used in `select_related` / `only()` chains and produce a distinct `OneToOneRel` object rather than the forward `OneToOneField`.
- **Chained reverse traversals**: Multiple levels of reverse relation traversal (e.g., `parent__child__grandchild` where each step is a reverse lookup) — each level must be independently normalized.
- **Mixed forward and reverse in the same query**: A single field-limiting call that includes both forward and reverse paths must handle both correctly without double-normalizing forward fields.
- **Self-referential models**: A model with a foreign key to itself where forward and reverse relations coexist on the same model — normalization must not confuse the two directions of distinct self-referential relationships.
- **Proxy models and inheritance**: Reverse relations through proxy or multi-table inheritance may introduce additional wrapper layers that must also be unwrapped to reach the canonical forward field.

## PR Examples
- django__django-16910