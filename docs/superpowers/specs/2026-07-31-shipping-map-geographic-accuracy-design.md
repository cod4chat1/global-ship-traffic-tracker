# Shipping Map Geographic Accuracy Design

## Objective

Replace the distorted hand-drawn world background with a geographically accurate,
lightweight map and improve how ports, straits, and canals are positioned and
represented. Preserve the existing Google Sheets dialog, filters, hover details,
and pinned 45-day trend view.

## Approved Approach

Use a simplified Natural Earth world coastline/country dataset as the static
basemap. Show ports at verified point coordinates. Show straits and canals as
short, oriented geographic corridor lines, with their activity marker centred on
the corridor. Do not attempt to maintain full administrative port boundaries,
anchorages, or provider-specific chokepoint polygons.

This approach prioritizes visible geographic accuracy, fast rendering, and honest
representation of the available aggregate PortWatch data.

## Geographic Sources

- Vendor a simplified Natural Earth land or country-boundary GeoJSON asset in the
  repository, including its source version and attribution.
- Verify port coordinates against an authoritative public port or geographic
  source where available. Coordinates represent a consistent port-centre or
  principal harbour location, not every terminal or anchorage.
- Verify strait and canal endpoints against authoritative public geographic
  references. Store the endpoints explicitly so their orientation is preserved.
- Record a coordinate-source note and verification date in configuration or an
  accompanying source manifest.

## Data Model

Each configured location retains its existing latitude and longitude. Add:

- `geometry_type`: `point` for ports or `corridor` for straits/canals;
- `geometry`: a compact coordinate array using GeoJSON longitude-latitude order;
- `coordinate_source`: source name or URL;
- `coordinate_verified_on`: ISO date; and
- `coordinate_note`: optional clarification such as port-centre or canal midpoint.

For corridors, the existing latitude and longitude remain the marker and tooltip
anchor. They are derived from the corridor midpoint rather than maintained as an
independent approximation.

The hidden `Map_Data` tab will include the geometry fields required by the map.
Daily traffic history and statistics remain unchanged.

## Map Rendering

- Use a real geographic projection suitable for a full-world view.
- Fit the Natural Earth geometry within the available SVG map area while
  preserving aspect ratio.
- Draw graticules from the projection rather than fixed screen coordinates.
- Render land from the vendored geographic geometry.
- Render ports as circles at projected point coordinates.
- Render straits and canals as short projected corridor lines with an activity
  symbol at the midpoint.
- Keep marker size tied to activity and marker colour tied to the selected metric.
- Retain collision handling only for labels or activity symbols; do not move the
  underlying geographic point or corridor.
- Add pan and zoom, with constrained scale and translation so users cannot lose
  the map entirely.
- Maintain a clear legend for ports, straits/canals, activity size, and selected
  metric colour.

## Interaction

Existing type, region, and metric filters remain. Hovering a port or corridor
shows the existing activity statistics and its verified geographic position.
Clicking pins the existing detail panel and 45-day trend. Dense areas become
readable through zoom rather than by permanently displacing coordinates.

## Performance and Reliability

- Simplify the Natural Earth geometry before bundling if necessary, but retain
  recognizable coastlines and major islands.
- Bundle all geographic assets with the Apps Script HTML or repository build;
  the map must not depend on a runtime map API, external tile server, or API key.
- Keep the rendered geographic payload small enough for responsive opening in the
  Google Sheets modal.
- Continue to treat the Python updater as the sole producer of map statistics.

## Error Handling

- Invalid or missing point coordinates omit only the affected marker and surface a
  readable data-quality warning.
- Invalid corridor geometry falls back to its verified midpoint marker and reports
  the fallback.
- Failure to load bundled basemap geometry shows a readable map error rather than
  reverting silently to the distorted hand-drawn polygons.
- Unsupported or ambiguous location geometry is not presented as exact.

## Testing and Verification

Automated checks will cover:

- valid longitude/latitude ranges and coordinate order;
- point-versus-corridor geometry validation;
- corridor midpoint derivation;
- map-data geometry serialization;
- projection output remaining within expected map bounds;
- fallback behavior for malformed geometry; and
- preservation of filters, tooltips, and pinned trends.

Visual verification will compare representative locations in each region,
including Singapore, Malacca, Hormuz, Suez, Panama, Gibraltar, Rotterdam,
Shanghai, Los Angeles, Santos, Durban, and Port Hedland. The review will confirm
recognizable coastlines, correct hemispheres, coastal placement, corridor
orientation, zoom behavior, and readable dense clusters.

## Rollout

1. Add and attribute the simplified Natural Earth asset.
2. Audit and source all active location coordinates and corridor endpoints.
3. Extend configuration and `Map_Data` with geometry metadata.
4. Replace the hand-drawn map renderer with projected geographic geometry.
5. Add constrained zoom/pan and corridor interactions.
6. Run automated and local visual checks.
7. Deploy the updated report data and bound Apps Script to the existing Sheet.
8. Verify the live map without changing the daily scheduler or notification rules.

## Acceptance Criteria

- The world outline is recognizable and no longer distorted by hand-drawn shapes.
- Every active port uses a verified point coordinate and appears in the correct
  coastal location.
- Every active strait or canal uses a verified oriented corridor or an explicitly
  documented midpoint fallback.
- Geographic markers are not permanently shifted to resolve collisions.
- Pan, zoom, filters, hover details, click-to-pin, and 45-day trends work in the
  Google Sheets dialog.
- The map requires no paid map service, runtime tile download, or API key.
- Existing daily updates and new-data-only notifications continue unchanged.
