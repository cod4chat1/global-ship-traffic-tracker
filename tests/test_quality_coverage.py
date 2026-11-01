import unittest
from datetime import date
from ship_traffic.aggregate import quality_rows

class QualityCoverageTests(unittest.TestCase):
    def row(self, area_id, availability="available", total=1, day="2026-10-25"):
        return {"area_id": area_id, "area_name": area_id.upper(), "observation_date": day,
                "availability": availability, "total": total, "unknown": 0, "avg_7d": 1, "avg_30d": 1}
    def check(self, rows, ids):
        return next(x for x in quality_rows(rows, date(2026,10,25), ids)
                    if x["check"] == "Partial/unavailable areas")
    def test_twelve_current_and_thirty_two_missing_warns_32(self):
        rows = [self.row(f"s{i}") for i in range(12)]
        ids = {r["area_id"] for r in rows} | {f"p{i}" for i in range(32)}
        result = self.check(rows, ids)
        self.assertEqual((result["status"], result["value"]), ("WARN",32))
        self.assertEqual(set(result["detail"].split(", ")), {f"p{i}" for i in range(32)})
    def test_retained_older_history_is_not_current(self):
        result = self.check([self.row("s"),self.row("p",day="2026-10-16")], {"s","p"})
        self.assertEqual((result["status"],result["value"],result["detail"]),("WARN",1,"P"))
    def test_null_and_partial_overlap_count_once_and_ignore_unconfigured(self):
        result = self.check([self.row("p","partial",None),self.row("p","partial",None),
                             self.row("other","unavailable",None)], {"p"})
        self.assertEqual((result["status"],result["value"]),("WARN",1))
    def test_fresh_zero_and_fixture_are_not_unavailable(self):
        result = self.check([self.row("p",total=0),self.row("s","fixture")], {"p","s"})
        self.assertEqual((result["status"],result["value"],result["detail"]),("PASS",0,"None"))
if __name__ == "__main__": unittest.main()
