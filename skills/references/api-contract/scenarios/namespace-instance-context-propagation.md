## Problem Description

In systems that support multiple named instances of the same component (e.g., multiple Django admin sites, multiple API routers, multiple app namespaces), URL or path resolution calls that omit an explicit instance context parameter silently fall back to the default instance. This causes generated links to always point to the default instance's URL prefix, even when the user is interacting with a non-default instance. The bug is invisible during single-instance development and testing, only surfacing when a second named instance is introduced.

## Root Cause Analysis

Namespace-aware URL resolvers treat the instance context parameter (e.g., `current_app`, `namespace`, `instance`) as optional, defaulting to the primary/default instance when it is not provided. This API design creates a **partial propagation** problem: some resolution calls in the codebase correctly pass the instance context while others do not, and the omission goes undetected because the default instance produces correct-looking results. The underlying principle is an **implicit assumption violation** — the developer assumes all instances share the same URL prefix or that context propagation is automatic, when in fact the resolution contract requires explicit context at every call site. The default parameter value masks the contract violation, turning what should be a loud failure into a silent wrong-output bug.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Generated URLs (links, redirects, breadcrumbs) always point to the default instance's URL prefix regardless of which instance the user is currently interacting with
  - The system works perfectly with a single (default) instance; the bug only manifests when a second named instance exists
  - Tests pass when run against the default instance but produce wrong output for non-default instances
  - The failure signal is **wrong output** (incorrect URLs), not an exception or crash

### 解决步骤
1. **Inventory all resolution call sites**: Search the codebase for every call that resolves a URL, route, or component reference within the multi-instance system (e.g., `reverse()`, `resolve()`, `{% url %}` template tags, `get_url()` helpers).
2. **Audit each call for explicit instance context**: For each resolution call, check whether it passes an instance-identifying parameter (`current_app`, `namespace`, `instance`, etc.). Flag any call that relies on the default.
3. **Trace the available context**: At each flagged call site, determine how to obtain the current instance's identity. Typically, the instance identity is already available on a parent object (e.g., `self.name` on an admin site class), on the request object (e.g., `request.current_app`), or passed through a function parameter chain.
4. **Propagate the context explicitly**: Add the instance context parameter to every flagged resolution call, sourcing it from the nearest available context using the same pattern already established by other correct calls in the codebase.
5. **Validate with multi-instance tests**: Create or extend tests that register at least two named instances of the component, then assert that each instance's resolution calls produce URLs scoped to that instance's own namespace/prefix.

### Why This Works

Namespace-aware resolution is a **contract**: every call must declare which instance it is resolving against. The default parameter value is a convenience for single-instance deployments, not a substitute for proper context propagation. By explicitly passing the instance context at every call site, we eliminate the ambiguity that causes the resolver to fall back to the default. This transforms the implicit assumption ("there is only one instance") into an explicit declaration ("resolve within *this* instance"), making the system correct for any number of named instances.

## Boundary Cases

- **Single-instance deployments**: Adding explicit context where the value matches the default must produce identical behavior — verify no regression when only one instance exists.
- **Nested namespaces**: When instances are nested (e.g., an app namespace inside an instance namespace), the full namespace chain must be propagated, not just the immediate instance name.
- **Request-less contexts**: Some resolution calls occur outside of a request cycle (e.g., management commands, background tasks, serializers). In these cases, there is no ambient `current_app` on a request object; the instance context must be threaded through explicitly or made a required parameter.
- **Dynamic instance registration**: If instances can be registered or removed at runtime, resolution calls must handle the case where the target instance no longer exists, rather than silently falling back to the default.
- **Template tag resolution**: URL resolution in templates (e.g., `{% url %}`) may require a different mechanism to propagate context (e.g., setting `request.current_app` in the view or passing it through the template context).

## PR Examples

- **django__django-14855**: Multiple Django admin sites where non-default admin site instances generated URLs pointing to the default admin's URL prefix because `reverse()` calls omitted the `current_app` parameter.