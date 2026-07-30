# Shipping Dashboard Optimization and World Map Design

## Objective

Improve the Global Ship Traffic Tracker by applying the strongest patterns from
the Malaysia Rainfall Tracker: compact focus controls, honest rolling
comparisons, multi-area analysis, clear data-quality signals, and an
interactive map opened inside Google Sheets.

The tracker will expand from 30 monitored locations toward a maximum of 50
without turning the visible workbook into a large control surface. Expansion
is conditional on reliable IMF PortWatch source matching and recent data
availability.

## Approved Decisions

- Keep GitHub Actions as the only scheduled updater.
- Keep IMF PortWatch as the free aggregate data source.
- Preserve silent successful runs when PortWatch has no newer observation date.
- Notify on new data and failures.
- Show ports and straits together on one world map with separate marker shapes
  and a `Both / Ports / Straits` filter.
- Use reliable port-activity measures, not label them as parked-vessel counts.
- Retain about 45 days of detailed data.
- Expand only to locations that pass provider-resolution and data-availability
  checks, up to 50 active locations.
- Keep all 50 locations available in the focus dropdown and map while limiting
  the visible comparison checkbox grid to a configurable priority subset.

## Scope

This change will:

- redesign the one-page dashboard around focus, period, type, region, and
  comparison controls;
- add a configurable comparison checkbox grid;
- correct rolling-window calculations so missing calendar days do not get
  compressed out;
- separate ports and straits in regional summaries;
- add current-condition and top-mover summaries;
- remove the hardcoded 30-area quality assertion;
- preflight and activate supported expansion locations;
- add hidden map data containing latest metrics and compact 45-day histories;
- add a bound Apps Script `Shipping Map` menu and interactive world map; and
- preserve the existing Sheet, Drive snapshot, schedule, and notification
  behavior.

This change will not:

- claim to measure exact ships at berth, anchorage, or waiting outside port;
- add a paid map provider;
- add a second scheduler or duplicate ingestion pipeline;
- fetch or store every PortWatch port;
- mix port calls and chokepoint crossings into one aggregate total; or
- add 90-day, 180-day, or all-history controls while only 45 days are retained.

## Location Expansion

### Activation rule

The implementation will begin with the existing 30 locations and evaluate a
prioritized candidate pool. A candidate becomes active only when all of the
following are true:

1. its PortWatch database name resolves unambiguously;
2. it has valid latitude and longitude;
3. it has recent non-null total activity;
4. its type is correctly identified as `port` or `strait`; and
5. adding it does not take the active configuration above 50 locations.

The deployment succeeds with any active count from 30 through 50. It will not
force unresolved or empty candidates into production merely to reach 50.

### Candidate priorities

Chokepoint candidates are evaluated first from:

- Singapore Strait;
- Dardanelles;
- Danish Straits;
- Lombok Strait;
- Sunda Strait; and
- Mozambique Channel.

Port candidates are evaluated from:

- Savannah;
- Paranagua;
- Dumai;
- Belawan;
- Laem Chabang;
- Ho Chi Minh / Cai Mep;
- Nhava Sheva / JNPT;
- Mundra;
- Kandla;
- Chennai;
- Colombo;
- Durban;
- Mombasa;
- Vancouver;
- Seattle / Tacoma;
- Melbourne;
- Port Hedland;
- Valencia;
- Algeciras;
- Piraeus;
- Kaohsiung; and
- Tokyo / Yokohama.

Matching uses normalized exact names first. Contains matching is allowed only
when it produces one unambiguous shortest candidate. The preflight report
records accepted and rejected candidates with reasons.

### Workbook-size limit

At 50 locations and a 45-day window, the detailed dataset is approximately
2,250 area-date rows. Ports and straits remain in separate visible data tabs.
This size is comfortably below the workbook's existing grid capacity and does
not require a database export into the visible dashboard.

## Dashboard Design

### Controls

The one-page `Dashboard` will contain:

- `Area type`: Port or Strait;
- `Region`: All, Africa, Asia, Europe, Middle East, North America, South
  America, or Oceania;
- `Focus location`: `All matching locations` or any active configured location;
- `Period`: 14, 30, or 45 days; and
- `Comparison selection`: native checkboxes for up to 16 priority locations.

Type and region filter the focus-location list. Selecting a specific location
drives the focus cards and focus chart. Selecting `All matching locations`
drives the headline cards and regional summary from the current type and
region filters; the focus chart then shows the highest-activity matching
location and labels that automatic choice explicitly.

The priority comparison subset is controlled by a configuration flag rather
than being hardcoded into formulas. The default subset spans major commodity,
container, and chokepoint locations across regions. More than eight checked
locations produces a visible crowding warning but is not blocked.

### Headline analysis

Focus cards will show:

- latest total daily activity or crossings;
- 7-day average;
- 30-day average;
- change versus 7-day average;
- change versus 30-day average;
- recent status relative to the 30-day average; and
- observation date and freshness.

Labels will explicitly say `Port activity` or `Strait crossings` according to
the selection. A permanent note will explain that exact parked-vessel counts
require licensed vessel-level AIS.

### Charts

The dashboard will contain:

1. **Focus location: actual versus moving averages**
   - daily actual;
   - 7-day average; and
   - 30-day average.
2. **Selected locations comparison**
   - one actual-activity line per checked location;
   - limited to the selected 14-, 30-, or 45-day period; and
   - port and strait series never combined into one summed series.
3. **Latest vessel-category mix**
   - bulk oil and gas;
   - bulk non-oil and gas;
   - container;
   - other cargo; and
   - unknown.

### Summary tables

The dashboard will show:

- a regional summary with separate Port and Strait rows;
- observed-location coverage for each row;
- the ten largest positive and negative deviations versus 30-day average; and
- data freshness and unresolved-location warnings.

A visible `Current_Conditions` tab will contain all active locations and their
latest metrics. The dashboard remains concise rather than displaying all 50
rows below the charts.

## Calculations

### Complete calendar windows

For area \(A\), date \(d\), and window \(n\):

```text
moving_average(A, d, n) =
    mean(total(A, d - n + 1), ..., total(A, d))
```

The result exists only when all \(n\) calendar dates have a valid observation.
Missing dates or null totals produce a blank value and `Insufficient data`.

### Deviations

```text
change_vs_7d = latest_total / average_7d - 1
change_vs_30d = latest_total / average_30d - 1
```

Division by zero or missing baselines produces a blank value.

### Recent status

Recent status is based on change versus the recent 30-day average, not a
seasonal historical normal:

- greater than `+10%`: `Above recent average`;
- `-10%` through `+10%`: `Near recent average`;
- less than `-10%`: `Below recent average`; and
- missing complete window: `Insufficient data`.

### Category shares

```text
category_share = category_count / total
```

Shares appear only when both values exist and total is positive. Unknown share
remains visible as a data-quality measure.

### Regional summaries

Port totals sum valid port calls by region. Strait totals sum valid
chokepoint crossings by region. Each summary also reports:

```text
coverage = observed configured locations / configured locations
```

Incomplete regional coverage is labelled and never presented as a complete
regional total.

## Hidden Map Data

The updater will create and maintain a hidden `Map_Data` tab with one row per
active location.

Columns:

- Area ID;
- Name;
- Type;
- Region;
- Latitude;
- Longitude;
- Observation date;
- Total activity;
- 7-day average;
- 30-day average;
- Change versus 7-day;
- Change versus 30-day;
- Recent status;
- Bulk O&G;
- Bulk non-O&G;
- Container;
- Other cargo;
- Unknown;
- Imports;
- Exports;
- Availability;
- Source;
- Source URL; and
- 45-day actual-history JSON.

The JSON history contains only date and total pairs for the location. It keeps
the map sparkline data compact and avoids an additional visible worksheet.

## Interactive World Map

### Runtime boundary

A bound Google Apps Script will:

- add a `Shipping Map` menu when the workbook opens;
- open a modal HTML-service dialog;
- read only the bound workbook's hidden `Map_Data`; and
- render the bundled world basemap, markers, filters, tooltips, and sparklines.

The daily Python workflow remains the sole data producer. Apps Script runs
only when the user opens or interacts with the map.

### Basemap

The repository will vendor an attributed, simplified Natural Earth
world-boundary asset and convert it to static SVG path data during the build.
Runtime map opening will not call Google Maps, download world geometry, or
require an API key.

### Markers and filters

- Ports use circles.
- Straits use diamonds.
- Marker size represents total activity.
- Marker colour represents the selected metric.
- Controls include:
  - Both / Ports / Straits;
  - region;
  - metric; and
  - vessel category.
- Metrics include:
  - total activity;
  - change versus 7-day average;
  - change versus 30-day average;
  - bulk O&G share; and
  - container share.

Closely spaced markers cluster at the world view and separate as the user
zooms. This specifically protects readability around Singapore, coastal
China, Northern Europe, Southern California, and the Gulf.

### Hover and click

Hovering displays:

- location, type, and region;
- observation date;
- total activity or crossings;
- 7-day and 30-day averages;
- deviations versus each average;
- category mix;
- imports and exports when available;
- availability and freshness; and
- the AIS limitation for parked-vessel counts.

Clicking pins a detail panel and renders the location's compact 45-day
sparkline. Clicking the background clears the pinned panel.

### Missing data

Missing or unresolved metrics use a grey marker. The tooltip explains
`Unavailable`, `Unresolved source`, `Stale observation`, or `Insufficient
rolling history` as applicable.

## Data Flow

```text
Existing configuration + expansion candidate pool
        |
        v
PortWatch source-resolution preflight
        |
        v
Active location configuration (maximum 50)
        |
        v
PortWatch daily observations
        |
        +--> complete 7-day and 30-day rolling calculations
        +--> category shares and recent status
        +--> separate port and strait regional summaries
        +--> quality and freshness checks
        |
        v
Google Sheet tables + Dashboard_Data + Map_Data
        |
        +--> native Sheet controls, cards, tables, and charts
        |
        +--> bound Apps Script interactive world map
```

## Refresh and Notification Behavior

The dashboard date remains the duplicate-delivery sentinel.

- A newer PortWatch report date updates the Sheet, snapshot, and map data, then
  sends the existing GitHub success alert.
- An equal or older report date exits successfully without changing the Sheet
  or Drive snapshot and sends no alert.
- Retrieval, calculation, Sheet, Drive, or map-data generation failures remain
  failures and send the existing GitHub failure alert.

Map UI failure does not stop ingestion because the map consumes already
written hidden data and has no scheduled trigger.

## Data Quality

The hardcoded `Expected 10 straits and 20 ports` rule will be removed.
Quality checks will instead report:

- configured active locations;
- accepted and rejected expansion candidates;
- locations observed on the target date;
- missing calendar dates;
- incomplete 7-day and 30-day windows;
- partial or unresolved locations;
- stale observations;
- average and maximum unknown-category share;
- missing import/export measures; and
- exact parked-vessel availability as `UNAVAILABLE` for PortWatch.

## Performance and Cost

- Active locations are capped at 50.
- Detailed history is capped at approximately 45 days.
- Only one latest map row and one compact history value are written per
  location.
- The map uses static repository-owned assets and Apps Script.
- No paid map API, AI call, or additional scheduled job is introduced.
- The implementation will record daily workflow duration and fail the rollout
  if typical refresh time exceeds ten minutes.

## Error Handling

- Ambiguous or unresolved candidate matches are rejected before activation.
- A newly failing existing location remains configured but is marked
  unavailable so the regression is visible.
- Incomplete rolling windows are blank, not calculated from fewer days.
- A missing or empty `Map_Data` tab displays a readable map-dialog error.
- Malformed history JSON affects only the corresponding sparkline.
- Map markers with invalid coordinates are omitted and reported by data
  quality.
- Existing focus and checkbox selections are preserved across automatic
  refreshes when their locations remain active.

## Testing

Automated tests will cover:

- exact and ambiguous PortWatch name resolution;
- expansion acceptance and rejection;
- active-location cap;
- dynamic configured-count quality checks;
- complete calendar rolling windows;
- missing-date and zero-baseline behavior;
- deviation and status thresholds;
- category reconciliation and shares;
- separate port and strait regional summaries;
- coverage ratios;
- dashboard selection preservation;
- map-data schema and history JSON;
- invalid coordinates and missing metrics;
- new-data and no-new-data notification paths; and
- map marker filtering, clustering inputs, and tooltip formatting.

Live verification will cover:

- approximately 30 to 50 active locations without workbook slowdown;
- all focus, region, type, period, and checkbox controls;
- focus and comparison chart updates;
- regional and top-mover summaries;
- `Current_Conditions`;
- Apps Script menu creation;
- one-time authorization;
- world-map rendering;
- port and strait marker distinction;
- region, type, metric, and category filters;
- hover details;
- pinned 45-day sparkline;
- overlapping-marker behavior in dense regions;
- preservation of selections after a scheduled refresh;
- a successful new-data delivery; and
- a successful silent unchanged-data run.

## Rollout

1. Implement and test calculations, dynamic quality checks, and map-data
   generation using the current 30 locations.
2. Add the dashboard controls, summaries, and `Current_Conditions`.
3. Add and locally validate the Apps Script world map.
4. Run the expansion preflight and activate passing candidates up to 50.
5. Publish code and Sheet structure.
6. Install the bound Apps Script in the existing tracker workbook.
7. Run a live new-data delivery and verify the Sheet, Drive snapshot, and map.
8. Run a duplicate-date delivery and verify that files and notifications remain
   unchanged.

## Acceptance Criteria

The feature is complete when:

- the tracker has at least the existing 30 and no more than 50 active,
  preflight-approved locations;
- the dashboard remains one-page and responsive;
- all active locations are accessible through the focus control and map;
- the comparison grid stays within 16 priority locations;
- rolling averages require complete calendar windows;
- regional port and strait measures remain separate;
- map hover and click expose the approved metrics;
- no parked-vessel claim is made from PortWatch data;
- a typical scheduled workflow finishes within ten minutes;
- new data updates the workbook and notifies;
- unchanged data makes no external writes and sends no notification; and
- the existing Google Sheet and Drive folder remain the production artifacts.
