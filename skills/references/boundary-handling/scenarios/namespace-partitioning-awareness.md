## Problem Description

When a system enforces global uniqueness of resource identifiers (e.g., table names, queue names, endpoint paths, cache keys) through validation logic, but the framework simultaneously supports namespace partitioning via routing or backend configuration (e.g., multiple databases, message brokers, or deployment targets), the validation produces false-positive errors. Configurations that are perfectly valid — because routing directs identically-named resources to separate, independent backends — are incorrectly rejected. This typically manifests as a regression: a previously working setup breaks after an upgrade introduces or tightens a uniqueness check that assumes a single, flat namespace.

## Root Cause Analysis

The core issue is a **single-namespace assumption** embedded in validation logic. When a developer writes a uniqueness check for resource identifiers, they naturally reason about one flat, global namespace. However, the framework's own infrastructure — database routers, backend selectors, partitioning configurations — can create multiple independent namespaces where the same identifier is legitimately valid in each partition.

This is an instance of **implicit assumption violation**: the validation logic implicitly assumes that all resources coexist in a single scope, while the routing/partitioning layer explicitly breaks that assumption by design. The abstraction is incomplete — the validation layer is unaware of (or ignores) the boundary-splitting behavior of the routing layer that sits alongside it.

The problem is compounded by the fact that routing decisions can be dynamic and context-dependent, making it impractical to fully resolve namespace assignments at static validation time. This means the fix cannot simply "ask the router" — it must use a lighter heuristic.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - A previously valid configuration produces hard validation errors after an upgrade (regression on edge case)
  - Error messages reference duplicate/conflicting resource identifiers across the entire application
  - The user's setup uses routing or backend configuration to direct resources to separate backends
  - The error is technically correct in a single-namespace world but incorrect given the partitioned topology

### 解决步骤
1. **Locate the validation rule** that enforces global uniqueness of the resource identifier. Confirm it operates over the entire application scope without considering namespace partitioning.
2. **Identify the partitioning mechanism** the framework provides (e.g., database routers, backend selectors, routing configuration). Determine how users signal that multiple independent namespaces are in play.
3. **Use the presence of routing configuration as a heuristic signal** rather than attempting to resolve routes at validation time. Check whether any non-default routing or multi-backend configuration is active.
4. **Downgrade the validation severity conditionally**:
   - When routing/partitioning configuration is detected → emit a **warning** instead of a hard error.
   - When no routing configuration is present (single namespace is the only possibility) → retain the original **hard error**.
5. **Enrich the warning message** with a contextual hint advising the developer to verify that their routing configuration ensures the conflicting resources are directed to separate backends.
6. **Preserve the original error code/identifier** so that tooling, CI pipelines, and suppression mechanisms can still reference it consistently regardless of severity level.

### Why This Works

The presence of routing configuration is a conservative, low-cost heuristic that avoids the complexity and fragility of actually resolving routes at validation time (which may depend on runtime state, request context, or dynamic logic). It correctly identifies the scenario where duplicate identifiers *may* be intentional without making a definitive claim.

Downgrading to a warning — rather than suppressing entirely — preserves visibility for genuine mistakes even in multi-backend setups. A developer who accidentally duplicates a resource name within a *single* backend's scope will still see the warning and can investigate. This strikes the right balance between safety (catching real errors) and flexibility (not blocking valid partitioned configurations).

The principle generalizes: **any time a system validates global uniqueness of identifiers but supports routing or partitioning that creates independent scopes, the validation must account for the partitioning mechanism or risk blocking valid configurations.**

## Boundary Cases
- **Routing configuration is present but misconfigured**: The warning correctly fires, and the contextual hint guides the developer to verify their routing — this is the intended safety net.
- **Dynamic or conditional routing**: Since routing decisions may depend on runtime context (e.g., which model, which request), static validation cannot definitively resolve them. The heuristic approach (detect config presence, warn) is the only safe strategy.
- **Default/no-op routers**: If the framework ships a default router that does not partition namespaces, its presence alone should not trigger the downgrade. Only non-default or explicitly configured routing should count.
- **Multiple resources with the same identifier routed to the same backend**: This is a genuine error even with routing configured — the warning preserves visibility for this case without hard-blocking the entire application.
- **Third-party or plugin-provided routers**: The heuristic should check for any registered routing configuration, not just built-in ones, to cover the ecosystem broadly.

## PR Examples
- django__django-11630