## Problem Description

When resources are acquired through an object reference chain (e.g., `object.parent.manager.connect(callback)`), the cleanup code often stores only a lightweight identifier (like a connection ID) and assumes it can re-traverse the same object chain at cleanup time to reach the resource manager. However, intermediate objects in that chain can be detached, nullified, or replaced between registration and cleanup — particularly during teardown sequences where the very event triggering cleanup is also the event severing the object graph. This results in `AttributeError: 'NoneType' object has no attribute ...` crashes during disconnect or teardown, where `None` represents a link that was valid at setup time but has since been severed.

This pattern is especially insidious because it works perfectly during normal operation (the happy path) and only manifests during edge-case lifecycle transitions — widget destruction, figure closure, reparenting, or garbage collection — making it a classic regression-on-edge-case failure.

## Root Cause Analysis

The underlying principle violated is **capture cleanup capability at acquisition time**. At the moment a resource is successfully acquired through an object chain, the code has maximum knowledge about how to release it. Deferring the resolution of the resource manager to cleanup time introduces an implicit assumption that the entire object graph remains stable and traversable indefinitely.

This assumption is false in practice because:

1. **Cleanup runs during instability**: Resource teardown is triggered precisely during the lifecycle transitions (detachment, destruction, reparenting) that invalidate the object graph. The cleanup callback fires *because* the graph is changing, yet it tries to use the now-invalid graph to perform its work.

2. **Asynchronous and external triggering**: Cleanup is often triggered by event callbacks, garbage collection hooks, or user interactions — not by the code that originally registered the resource. The registering code cannot guarantee sequencing.

3. **Cognitive trap of graph stability**: Developers naturally model object relationships as stable because they observe stability during development and testing. The fragility only surfaces under specific teardown orderings or edge-case user interactions.

## Solution Strategy

### 识别信号
- 观测到的现象: `AttributeError: 'NoneType' object has no attribute <method>` during teardown, disconnect, or callback-driven cleanup
- The `None` value corresponds to an intermediate object in a reference chain (e.g., `self.canvas.manager` where `canvas` or `manager` is `None`)
- The crash occurs in event-driven or lifecycle-triggered code paths, not during normal operation
- The registration code (connect/subscribe) and cleanup code (disconnect/unsubscribe) traverse the same multi-hop object chain, but only the registration is guaranteed to run when the chain is intact

### 解决步骤
1. **Audit all resource acquisition sites**: Identify every place where a resource is registered (callback connected, handle opened, subscription created) by traversing an object reference chain, and where only a raw identifier (connection ID, handle number) is stored for later cleanup.

2. **Capture the resource manager at acquisition time**: At the point of successful registration, resolve and store a direct reference to the resource manager — or better yet, create a pre-bound cleanup callable (e.g., `functools.partial(manager.disconnect, cid)` or a closure) that encapsulates everything needed for disconnection.

3. **Replace deferred-resolution cleanup with pre-bound disconnectors**: Store these self-contained disconnector callables as the primary cleanup mechanism. The cleanup code should invoke the stored callable directly, never re-traversing the object graph.

4. **Preserve backward compatibility via computed properties**: If external code depends on raw identifiers (e.g., connection IDs exposed as public attributes), expose them as computed properties derived from the stored disconnectors rather than as the primary storage.

5. **Simplify dynamic connect/disconnect patterns**: Where sub-resources are dynamically connected and disconnected (e.g., motion event handlers connected only during a drag operation), evaluate whether they can be replaced with permanently registered handlers that use a guard flag. This eliminates additional cleanup paths that face the same stale-reference problem.

6. **Add defensive checks at cleanup boundaries**: As a belt-and-suspenders measure, add `None` checks or try/except guards around any remaining cleanup code that must traverse object references, logging warnings rather than crashing.

### Why This Works

Pre-bound disconnectors follow the **principle of least coupling**: the cleanup operation depends only on the captured reference to the resource manager, not on the continued integrity of an arbitrarily deep object graph. By encoding cleanup knowledge at the moment of maximum certainty (acquisition time), the code becomes immune to subsequent graph mutations. This is analogous to how context managers capture the resource at `__enter__` time rather than re-resolving it at `__exit__` time.

## Boundary Cases
- **Circular reference prevention**: Capturing direct references to resource managers in closures or partials can create reference cycles that prevent garbage collection. Use `weakref` where appropriate, with a no-op fallback if the referent has been collected.
- **Multiple cleanup invocations**: Pre-bound disconnectors may be called more than once (e.g., explicit cleanup followed by garbage collection). Ensure idempotency — disconnecting an already-disconnected resource should be a no-op, not an error.
- **Manager replacement**: If the resource manager itself can be replaced (not just nullified) between registration and cleanup, a captured reference to the old manager is still correct — you want to disconnect from the manager you connected to, not the current one.
- **Thread safety**: If registration and cleanup can occur on different threads, the captured reference must be accessed safely. The pre-bound callable pattern naturally serializes the needed state at creation time, reducing (but not eliminating) threading concerns.
- **Backward-compatible attribute access**: External code that directly reads stored connection IDs (e.g., `obj._cid`) must continue to work. Expose these as properties that extract the ID from the stored disconnector, or maintain both the disconnector and the raw ID.

## PR Examples
- **matplotlib__matplotlib-25442**: Event callback disconnection traversed `self.canvas.manager` at cleanup time, but `canvas.manager` could be `None` when a figure was being closed. Fixed by capturing the manager reference (or a bound disconnect method) at the time callbacks were registered, making cleanup independent of the object graph's state during teardown.