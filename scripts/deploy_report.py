from __future__ import annotations

import argparse
import json
from pathlib import Path

from ship_traffic.google_delivery import deliver


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy a previously validated report to Google Sheets and Drive"
    )
    parser.add_argument("--report", required=True)
    parser.add_argument("--screenshot", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.report).read_text(encoding="utf-8"))
    result = deliver(payload, args.screenshot)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
