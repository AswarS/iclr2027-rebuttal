## Problem Description

When an entity (such as a UI widget, event handler, or session object) acquires an exclusive resource — like an input capture, mutex lock, focus ownership, or channel reservation — through a side-channel subsystem (e.g., an event dispatcher or lock manager), and that entity is subsequently destroyed or removed from its parent container, the exclusive resource may become permanently orphaned. The container's teardown logic cleans up structural relationships (parent-child links, rendering trees) but fails to notify the independent subsystem that manages the exclusive state. As a result, no other entity can ever acquire that resource, leading to deadlocks, frozen input, or permanently inconsistent application state.

This pattern is particularly insidious because the exclusive capture is typically acquired transiently (e.g., on a mouse-down event) and is expected to be released by a corresponding event (e.g., mouse-up) that **never arrives** because the entity was destroyed mid-interaction.

## Root Cause Analysis

The fundamental issue is a **state desynchronization between two independent subsystems**: the structural container hierarchy and the exclusive-resource management system.

Developers naturally build a mental model where an entity's lifecycle is fully governed by its membership in a container — "removed from parent = fully cleaned up." This assumption is correct for state that is intrinsic to the container relationship (rendering order, layout participation, parent references), but it is **incorrect for state registered with orthogonal subsystems** that maintain their own bookkeeping independently.

Exclusive captures and locks are **side-channel state**. They live in a separate subsystem (event dispatcher, input manager, lock table) that has no automatic awareness of container membership changes. The teardown path must explicitly bridge this gap. Without that bridge, the removal creates an orphaned reference: the resource manager still points to a defunct entity that will never call the release method, and all future consumers are permanently blocked.

The problem is compounded by the fact that bulk operations (e.g., "clear all children," "reset container") often delegate to the same per-entity removal logic, so a single missing release call in the centralized removal chokepoint silently breaks every removal pathway at once.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Deadlock or frozen interaction**: After removing/clearing an entity, subsequent entities of the same type can no longer receive input or acquire the same exclusive resource.
  - **Inconsistent state**: The resource manager reports a resource as "held" by an entity that no longer exists in any container.
  - **Reproduction requires mid-interaction destruction**: The bug only manifests when an entity is removed while it holds the exclusive capture (e.g., removing a widget from within its own click callback), making it intermittent and hard to catch in basic testing.

### 解决步骤

1. **Inventory all exclusive resources an entity can acquire.** Audit the entity's class and its interactions with external subsystems. Identify every exclusive or singleton resource it can hold: input captures, mouse grabs, focus ownership, lock table entries, channel reservations, modal state flags.

2. **Trace every destruction/removal pathway.** Map not just explicit `dispose()` or `remove()` calls, but also bulk operations like "clear all children," "reset container," "replace contents," and any implicit removal triggered by lifecycle events or framework hooks.

3. **Locate the centralized removal chokepoint.** Find the single method through which all removal paths converge (e.g., `remove()`, `_remove_from_parent()`, `discard()`). This is where the fix belongs — not in individual widget callbacks or specific use-case code.

4. **Add unconditional release calls at the chokepoint.** For each exclusive resource identified in step 1, add an explicit release call in the centralized removal method. **Prefer unconditional release over conditional checks** — if the release operation is a safe no-op when the entity doesn't hold the resource (e.g., `release_if_held(entity)` or a guard inside the release method), calling it unconditionally is simpler, more robust, and eliminates the risk of stale condition checks.

5. **Verify with a mid-interaction destruction test.** Write a test that:
   - Has the entity acquire the exclusive capture (e.g., simulate mouse-down).
   - Removes/destroys the entity from within the callback context (or immediately after, before the release event).
   - Attempts to have a new entity acquire the same exclusive resource.
   - Asserts that the new entity succeeds without deadlock or error.

### Why This Works

By placing the release in the centralized removal path, every removal scenario — programmatic, user-initiated, bulk clear, or callback-triggered — gets the cleanup for free. This eliminates the class of bugs where a new removal pathway is added later without remembering to release side-channel state. The unconditional release pattern further reduces fragility: there is no conditional logic that can drift out of sync with the acquisition logic, and the worst case (releasing a resource not held) is a harmless no-op rather than a silent omission.

## Boundary Cases

- **Re-entrant removal**: The entity's release callback itself triggers another removal or state change. Ensure the release and removal logic is re-entrant-safe or uses guards to prevent infinite recursion.
- **Bulk clear operations**: A "clear all" method that iterates over children and removes them one by one must not break if releasing one entity's capture triggers side effects on siblings (e.g., focus moving to the next widget, which is about to be removed too).
- **Entity removed but not garbage collected**: If the resource manager holds a strong reference to the entity (for the capture), the entity may never be GC'd even after container removal. The release call must also clear the resource manager's reference.
- **Multiple exclusive resources held simultaneously**: An entity may hold more than one exclusive resource at a time (e.g., mouse capture AND keyboard focus). The teardown must release all of them, not just the most obvious one.
- **Release called on an entity that never acquired the resource**: The release operation must be a safe no-op in this case. If it raises an exception or has side effects, the unconditional-release strategy will cause regressions for entities that were removed without ever interacting with the exclusive subsystem.
- **Thread safety**: If the exclusive resource can be acquired and released from different threads, the release in the removal path must use the same synchronization primitives as the normal acquire/release path.

## PR Examples

- **matplotlib__matplotlib-25433**: A UI widget (e.g., a Slider or Button) acquires mouse capture via the event dispatch system. When the figure is cleared (`fig.clf()`) or the axes containing the widget is removed, the widget's structural references are cleaned up but the mouse capture in the event manager is not released. Subsequent widgets on the new axes can never receive mouse events because the capture is permanently held by the defunct widget. The fix adds an unconditional release of the mouse capture in the centralized widget removal/teardown path.