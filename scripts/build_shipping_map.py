from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def build() -> Path:
    template = (ROOT / "apps_script" / "ShippingMap.template.html").read_text(
        encoding="utf-8"
    )
    land = json.loads(
        (ROOT / "assets" / "maps" / "natural-earth-110m-land.geojson").read_text(
            encoding="utf-8"
        )
    )
    land_source = json.dumps(land, separators=(",", ":"))
    output = template.replace("/*__LAND_GEOJSON__*/", land_source)
    if "/*__LAND_GEOJSON__*/" in output:
        raise RuntimeError("Shipping map template placeholders were not replaced")
    destination = ROOT / "apps_script" / "ShippingMap.html"
    destination.write_text(output, encoding="utf-8")
    d3_source = (ROOT / "assets" / "maps" / "d3.v7.min.js").read_text(
        encoding="utf-8"
    )
    midpoint = len(d3_source) // 2
    d3_parts = (d3_source[:midpoint], d3_source[midpoint:])
    for index, part in enumerate(d3_parts, start=1):
        source = f"const D3_CODE_{index} = {json.dumps(part)};\n"
        (ROOT / "apps_script" / f"D3Code{index}.gs").write_text(
            source, encoding="utf-8"
        )

    preview = output.replace(
        "<script>(0, eval)(<?!= getD3SourceLiteral(); ?>);</script>",
        f"<script>{d3_source}</script>",
    )
    preview_path = ROOT / "artifacts" / "ShippingMap.preview.html"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_text(preview, encoding="utf-8")
    return destination


if __name__ == "__main__":
    built = build()
    print(f"Built {built} ({built.stat().st_size} bytes)")
