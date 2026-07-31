# Shipping map assets

- `ne_110m_land.zip` is the Natural Earth 1:110m land dataset downloaded from
  `https://naturalearth.s3.amazonaws.com/110m_physical/ne_110m_land.zip`.
- `natural-earth-110m-land.geojson` is a property-free GeoJSON conversion of that
  dataset for the bundled Google Sheets map.
- `d3.v7.min.js` is the vendored official D3 v7 browser build from
  `https://d3js.org/d3.v7.min.js`. The build splits it between two Apps Script
  HTML partials so the browser downloads no runtime library.

Natural Earth data is public domain. D3 is distributed under the ISC license.
Both assets are bundled so opening the map makes no runtime tile, CDN, or API-key
request.

Port and chokepoint source points are synchronized from the IMF PortWatch ArcGIS
database by `scripts/sync_map_geography.py`. Strait/canal lines are orientation
indicators, not administrative boundaries or PortWatch counting geofences.
