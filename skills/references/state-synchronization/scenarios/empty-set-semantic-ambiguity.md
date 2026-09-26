## Problem Description

When a system uses an empty collection as a sentinel value meaning "no restriction" (i.e., include everything), operations that progressively remove elements from that collection can fully deplete it, causing the empty result to be misinterpreted as "no restriction" instead of "maximum restriction." This is a **semantic collision** — two fundamentally opposite intents (nothing was ever specified vs. everything was explicitly removed) map to the same representation (an empty set), and the system silently picks the wrong interpretation.

This pattern arises in any dual-mode set-based constraint system (whitelist/blacklist, include/exclude, allow/deny) where emptiness in one mode carries a default semantic meaning. The ambiguity is latent and only surfaces when a subtraction operation happens to remove *all* elements, which is a boundary condition developers rarely anticipate.

## Root Cause Analysis

The root cause is **sentinel value collision under set arithmetic**. The system designates the empty set in "include" mode as a sentinel meaning "no filter applied — include everything." This works correctly when the user has never specified any inclusions. However, when the user specifies inclusions and then chains exclusions that fully deplete the inclusion set, the result is also an empty set — but now it means "nothing should be included beyond mandatory items."

The system cannot distinguish between these two states because it uses a single representation (empty collection) for both. This is a form of **implicit assumption violation**: the original design assumed the include set would only grow or shrink partially, never reaching zero through subtraction. It is also a **symmetry-breaking** problem — addition and subtraction are not symmetric in their edge behavior because subtraction can hit the sentinel boundary while addition cannot.

## Solution Strategy

### 识别信号
- 观测到的现象: **Wrong output / regression on edge case** — when all items are removed from an include-set via chained exclusion operations, the system silently loads *everything* instead of loading *nothing* (beyond mandatory defaults). The behavior is the exact opposite of user intent, with no error or warning.

### 解决步骤
1. **Audit all representation modes where an empty collection has a default semantic meaning.** Map out every code path where an empty whitelist/include-set is interpreted as "no restriction." Document the sentinel semantics explicitly.

2. **Instrument every subtraction/removal operation on these collections.** At each point where elements are removed from the set, add a post-condition check: has the collection become empty as a result of this subtraction?

3. **Detect full depletion and switch representation modes.** When the working set is fully depleted through subtraction (not through never being populated), convert to the dual representation: transform the removed items into explicit entries in the opposite mode (e.g., convert an empty include-set into a populated exclude-set containing the removed items).

4. **Handle superset subtraction correctly.** If the subtraction set contains items not present in the original include-set, preserve those extra items as explicit exclusion entries in the new mode. This ensures that exclusions of items the user never explicitly included are still honored.

5. **Validate with boundary-specific tests.** Add test cases that cover: (a) removing exactly all items from the include set, (b) removing a superset of the include set, (c) removing a strict subset (existing behavior should be unchanged), and (d) chaining multiple removal operations that cumulatively deplete the set.

### Why This Works

Switching representation modes when the set empties **eliminates the semantic ambiguity entirely**. Instead of an empty whitelist (which the system reads as "everything"), you produce a populated blacklist (which the system reads as "exclude these specific items"). The system already has well-defined behavior for a populated blacklist, so no new interpretation logic is needed — you are simply routing the edge case into an existing, unambiguous code path. The key insight is that the *history* of how the empty set was reached matters, and encoding that history into the representation mode preserves the user's intent.

## Boundary Cases
- **Exact depletion**: The subtraction set is identical to the include set — all items are removed, and the result must mean "include nothing beyond defaults," not "include everything."
- **Superset subtraction**: The subtraction set is a strict superset of the include set — extra excluded items must still be tracked as explicit exclusions in the new mode.
- **Incremental depletion**: Multiple chained subtraction operations that individually leave a non-empty set but cumulatively empty it — each intermediate state must be checked.
- **Empty initial state**: The include set was never populated (true "no restriction") — this must remain unaffected by the fix and continue to mean "include everything."
- **Subtraction from an already-switched mode**: If the system has already transitioned to exclude mode, further subtractions should add to the exclude set rather than triggering another mode switch.

## PR Examples
- django__django-14667