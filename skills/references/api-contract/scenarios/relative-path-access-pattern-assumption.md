## Problem Description

When relative URLs or paths are constructed within detail/edit views to navigate to related sub-resources (e.g., `../password/`, `../settings/`), they encode an implicit assumption about the current URL's structure — specifically, the depth and format of the identifier segment. If the same view can be reached through different URL patterns (e.g., via primary key, UUID, slug, or a foreign key's `to_field`), the relative path may resolve incorrectly, leading to 404 errors or broken navigation. This is a classic **leaky abstraction** where the internal link construction leaks assumptions about URL topology that are not guaranteed by the routing contract.

## Root Cause Analysis

Relative paths like `../sub-resource/` work by navigating "up" one URL segment from the current location. This implicitly assumes that the current URL always has the same number of segments and that the identifier occupying a particular segment has a predictable format. However, when a view is accessible through multiple URL configurations — for example, when a model admin uses different lookup fields depending on the relationship (`to_field` on a ForeignKey, slug-based access, etc.) — the identifier segment can change in both value and type. A path constructed as `../password/` from `/admin/users/42/change/` works correctly, but the same relative path from `/admin/users/some-uuid-value/change/` may land on an entirely different and invalid URL. The root cause is the **implicit assumption of uniform access patterns**: the developer builds navigation links based on the most common or default access path without accounting for the variability introduced by the routing layer's abstraction over identifier types.

## Solution Strategy

### 识别信号
- 观测到的现象: **Wrong output / 404 errors** when navigating to sub-resource links (e.g., password change, inline edit) from a detail page that was reached via a non-default lookup field. **Regression on edge cases** where the page works fine when accessed by primary key but breaks when accessed through a foreign key relationship using `to_field` or an alternative identifier.

### 解决步骤
1. **Audit all relative path constructions** in detail/edit views — search for patterns like `"../"`, `reverse()` calls that append relative segments, or template-level URL construction that assumes fixed URL depth.
2. **Map the URL access patterns** for each view: determine whether the view can be reached via multiple identifier types (PK, UUID, slug, `to_field` values). Pay special attention to admin views, generic detail views, and any view registered under multiple URL patterns.
3. **Replace relative paths with canonically-rooted paths**: instead of `../sub-resource/`, navigate up to a stable, known ancestor in the URL hierarchy and reconstruct the path using the canonical identifier (typically the primary key). For example, replace `../password/` with `../../{instance.pk}/password/`, ensuring the target view always receives the identifier it expects.
4. **Validate that the target sub-resource view resolves using the canonical identifier**: confirm that the destination URL pattern accepts the identifier type you are embedding in the constructed path. Add test cases covering access via each supported lookup field to prevent regressions.

### Why This Works

By anchoring navigation to a stable ancestor path and explicitly using the canonical identifier (which the target view is guaranteed to accept), the constructed URL becomes independent of how the current page was reached. This eliminates the implicit coupling between the current URL's structure and the outgoing link, making the navigation robust against variations in lookup field type, URL depth, or routing configuration. The principle is: **never assume URL topology is fixed when the routing layer permits variability — always construct outgoing links from invariants (canonical identifiers and absolute or well-anchored paths).**

## Boundary Cases
- **Multi-segment identifiers**: If the lookup field value itself contains slashes or special characters (e.g., encoded slugs), relative path traversal can break in unexpected ways even when the depth appears correct.
- **Nested inlines or multi-level sub-resources**: When navigating more than one level deep (e.g., from an inline edit to a related object's password change), each level of relative path compounds the assumption risk — all intermediate segments must be accounted for.
- **Custom `to_field` on ForeignKey relationships**: Admin views that use `to_field` to look up related objects will substitute a non-PK value into the URL, changing the segment that relative paths depend on.
- **URL patterns with optional trailing slashes or varying prefixes**: Middleware or URL configuration differences across environments (e.g., `APPEND_SLASH` settings) can shift the effective depth of relative paths.
- **Reverse URL resolution fallback**: If `reverse()` is available and reliable for the target view, prefer it over manual path construction entirely, as it is immune to structural assumptions.

## PR Examples
- django__django-16139