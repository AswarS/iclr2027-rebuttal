## Problem Description

When an optimizer or reducer compresses sequences of operations into a single canonical form (e.g., folding post-creation modifications into the creation operation itself), its reduction rules are written as a closed, enumerated set covering only the operation types known at the time of writing. As new operation types are introduced — or existing options are deprecated in favor of new operation representations — novel operation sequences appear that the optimizer has never encountered. These sequences pass through the optimizer unreduced, leaving deprecated options, redundant operations, or verbose artifacts in the optimized output. This is a form of **complexity-escalation blindness**: the implicit assumption that the current set of reduction rules is permanently complete.

## Root Cause Analysis

The fundamental issue is that reduction/optimization rule sets form an **extensible contract** that must evolve in lockstep with the operation vocabulary they consume. When a new operation type is added or a deprecation migration path introduces a transitional operation pattern (e.g., converting a legacy indexed option into a first-class index operation), the optimizer's rule table is not revisited. This creates a gap:

1. **Enumeration staleness**: The reducer only handles operation types that existed when it was first authored. New types silently fall through.
2. **Deprecation-path blindness**: Deprecation transitions introduce *new* operation sequences (old-style → new-style conversions) that are semantically absorbable into a creation operation but are not recognized by the existing rules.
3. **Residual empty collections**: Even when partial reduction occurs, removing entries from a deprecated option set may leave behind an empty collection. Many systems treat the *presence* of a key — even with an empty value — as semantically meaningful, continuing to emit warnings or trigger legacy behavior.

The root principle: **any time the set of composable operations grows, the optimizer's reduction rules must grow with it, or the optimizer silently degrades.**

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Deprecated options or redundant operations survive in optimized/squashed output.
  - Deprecation warnings are emitted from output that should have been fully reduced.
  - Squashed migration files contain operations that could have been folded into a preceding creation operation.
  - Empty deprecated option keys (e.g., `index_together = set()`) persist in the canonical creation operation.

### 解决步骤

1. **Audit the full operation vocabulary against the reducer's rule table.** Enumerate all operation types that can logically follow a creation operation and be semantically absorbed into it. Do not limit this to the types that existed when the optimizer was first written — include all current and recently-added types, especially those introduced as part of deprecation paths.

2. **Add reduction rules for each newly-absorbable operation type**, dispatching by semantic category:
   - **Addition operations** (e.g., `AddIndex`, `AddConstraint`): Append the entity to the creation operation's options or field list.
   - **Removal operations** (e.g., `RemoveIndex`, `RemoveConstraint`): Filter out the named entity from the creation operation's options.
   - **Rename/transition operations** (e.g., `RenameIndex` used to transition from `index_together` to named indexes): Detect the distinguishing attribute that marks the operation as a *transition* (e.g., presence of `old_fields` rather than `old_name`) and convert the deprecated representation into the modern one within the creation operation's options.

3. **Recognize deprecation-transition patterns explicitly.** When a transition operation carries a distinguishing marker (e.g., `old_fields` indicating it migrates a legacy composite option rather than simply renaming an existing named entity), branch into transition-specific logic that:
   - Removes the matching entry from the deprecated option set.
   - Adds the modern equivalent (e.g., a named `Index` object) to the appropriate option list.

4. **Clean up empty deprecated option keys.** After removing entries from a deprecated option set, check whether the set is now empty. If so, remove the option key entirely from the creation operation rather than leaving an empty collection, which may still trigger warnings or legacy behavior.

5. **Group related operation types under a common base-class check** where possible, then dispatch to type-specific handling within. This reduces redundant type checks and makes it structurally obvious when a new subclass is added but not yet handled.

### Why This Works

The optimizer's reduction rules are not a one-time artifact — they are a **living contract** that must mirror the full space of composable operations. By systematically auditing the operation vocabulary each time it changes, adding rules for new absorbable types, and ensuring deprecated option keys are fully cleaned up (not just partially reduced), the optimizer maintains its invariant: the output is the minimal canonical representation with no deprecated artifacts. Grouping by base class makes future omissions structurally visible during code review.

## Boundary Cases

- **Transition operations vs. simple rename operations on the same type**: A single operation class (e.g., `RenameIndex`) may serve dual purposes — simple renames (identified by `old_name`) and deprecation transitions (identified by `old_fields`). The reducer must distinguish these by checking for the transition-specific attribute, not just the operation class.
- **Empty deprecated option sets after reduction**: Removing the last entry from a deprecated option (e.g., `index_together`) must result in the key being deleted entirely, not left as an empty set/list, since downstream systems may interpret key-presence as meaningful.
- **Multiple deprecated entries reduced in sequence**: When several transition operations target the same deprecated option set in succession, each reduction must operate on the already-partially-reduced creation operation, not the original. Order-dependent correctness matters.
- **New operation types added in the future**: The pattern will recur. Consider adding defensive logging or warnings when the optimizer encounters an operation type it has no rule for following a creation operation, to surface the gap early.
- **Operations targeting entities not present in the creation operation**: A removal or rename operation that references an entity not found in the creation operation's options should not silently no-op — it may indicate an upstream bug or an out-of-order operation sequence.

## PR Examples

- **django__django-16820**: The migration optimizer's `CreateModel` reducer did not handle `RenameIndex` operations used as `index_together` deprecation transitions. This left deprecated `index_together` entries (including empty sets) in squashed migrations, producing deprecation warnings. The fix added reduction rules to recognize the transition pattern (via `old_fields`), convert deprecated entries to modern `Index` objects, and remove the `index_together` key entirely when emptied.