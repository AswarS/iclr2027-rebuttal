## Problem Description

When a system provides both a **general-purpose listing** (e.g., "all members") and **specialized filtered listings** (e.g., "functions only", "classes only") of the same underlying collection, a common defect arises where the general listing bypasses configuration-driven filtering that the specialized listings correctly honor. Users observe that a configuration flag (such as "exclude imported members") works perfectly when viewing specialized sub-listings but is silently ignored when viewing the aggregated/general listing. This creates an inconsistent state where the same item appears excluded in one view but present in another, undermining trust in the configuration surface.

## Root Cause Analysis

The root cause is a **symmetry break in abstraction**: specialized listings are built through a deliberate filtering pipeline (import detection, skip-event hooks, visibility checks), while the general listing is populated via a raw enumeration mechanism (e.g., `dir()`, `vars()`, dictionary iteration, or a simple loop over all attributes) that predates or was never updated to incorporate the same filtering logic.

This happens because developers naturally focus filtering effort on the specialized, typed listings — which feel like the "real" feature — and treat the general listing as a low-level dump or internal convenience. The implicit assumption is that the general listing is either secondary or that consumers will apply their own filtering downstream. In practice, template authors and end users prefer the general listing for its simplicity and expect it to be a proper superset that honors the same rules. The filtering logic lives in multiple ad-hoc locations rather than a single shared component, so when a new configuration flag is introduced, it gets wired into some code paths but not all — a classic **incomplete abstraction** problem.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Wrong output**: The general listing includes items (e.g., imported members) that the configuration explicitly says should be excluded.
  - **Inconsistent state**: Specialized listings (functions, classes, etc.) correctly exclude items, but the general "all members" listing still shows them — the same configuration flag produces different behavior depending on which view is queried.
  - Users report that a configuration option "doesn't work" even though it partially works in specific sub-views.

### 解决步骤

1. **Map all code paths that produce listings from the same collection.** Identify every place the underlying data (e.g., module attributes, class members) is enumerated and surfaced to consumers. Distinguish between the general listing path and each specialized listing path.

2. **Audit filtering logic per path.** For each specialized listing, catalog the filtering steps applied: provenance checks (imported vs. native), configuration-flag evaluation, event/hook-based skip logic, visibility rules. Then inspect the general listing path and identify which of these steps are missing — look specifically for raw enumeration calls (`dir()`, `vars()`, bare iteration) that skip the pipeline entirely.

3. **Extract filtering into a shared, reusable component.** Consolidate the filtering logic into a single scanner, utility function, or filter pipeline that encapsulates: (a) determining item provenance, (b) applying all configuration-driven inclusion/exclusion rules, and (c) honoring extension points or event hooks for custom skip logic. Parameterize it so both general and specialized listings can invoke it with their respective context.

4. **Replace raw enumeration in the general listing** with a call to the shared filtering component, passing the same configuration flags that the specialized listings use. Ensure the general listing is now a true union of the specialized listings, not an unfiltered superset.

5. **Add targeted tests.** Write tests that assert the general listing respects each configuration flag — especially the "off" / exclusion state. Include a test that compares the union of all specialized listings against the general listing to enforce symmetry as an invariant.

### Why This Works

Multiple views of the same underlying data must all pass through the same filtering pipeline to maintain consistency. By extracting filtering into a single shared component, you eliminate the possibility of one listing drifting out of sync with the others when new configuration flags are added or existing logic is modified. The shared component makes the filtering behavior discoverable, testable in isolation, and impossible to accidentally bypass. This transforms a fragile multi-site invariant ("every listing must remember to filter") into a structural guarantee ("there is only one filtering path").

## Boundary Cases

- **Empty general listing after filtering**: When the configuration excludes all items (e.g., every member is imported), the general listing should return empty rather than falling back to an unfiltered enumeration.
- **Extension hooks that conditionally skip items**: Custom skip-event handlers may behave differently depending on the listing context (general vs. specialized). The shared component must propagate sufficient context so hooks can make informed decisions without breaking symmetry.
- **Items that belong to multiple specialized categories**: If an item appears in more than one specialized listing (e.g., a callable class), the general listing must include it exactly once while still applying the same filtering rules.
- **Dynamically generated members**: Items created at runtime (e.g., via `__getattr__`) may appear in `dir()` but not in the filtered pipeline. The shared component must have a consistent policy for these.
- **Backward compatibility**: Consumers relying on the old unfiltered general listing may break when filtering is applied. Consider whether a migration path or explicit "unfiltered" mode is needed.

## PR Examples

- **sphinx-doc__sphinx-7686**: Sphinx's autodoc module provided both a general "all members" directive and specialized directives (autofunction, autoclass, etc.). A configuration flag for excluding imported members was honored by the specialized directives but ignored by the general listing, which used raw `dir()`-based enumeration. The fix involved routing the general listing through the same member-scanning and filtering logic used by the specialized directives.