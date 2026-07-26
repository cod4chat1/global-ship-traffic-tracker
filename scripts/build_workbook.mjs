import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [reportPath, outputPath, previewDir] = process.argv.slice(2);
if (!reportPath || !outputPath || !previewDir) {
  throw new Error("Usage: build_workbook.mjs <report.json> <output.xlsx> <preview-dir>");
}

const report = JSON.parse(await fs.readFile(reportPath, "utf8"));
const workbook = Workbook.create();
const dashboard = workbook.worksheets.add("Dashboard");
const straits = workbook.worksheets.add("Daily_Strait_Traffic");
const ports = workbook.worksheets.add("Daily_Port_Activity");
const quality = workbook.worksheets.add("Data_Quality");
const config = workbook.worksheets.add("Area_Config");
const runLog = workbook.worksheets.add("Run_Log");
const dashboardData = workbook.worksheets.add("Dashboard_Data");
await workbook.comments.setSelf({ displayName: "User" });

const headerFormat = {
  fill: "#E5E7EB",
  font: { bold: true, color: "#111827" },
  borders: { preset: "outside", style: "thin", color: "#CBD5E1" },
};
const titleFormat = {
  fill: "#F3F4F6",
  font: { bold: true, color: "#111827", size: 18 },
};
const controlFormat = {
  fill: "#EFF6FF",
  font: { bold: true, color: "#1E3A8A" },
  borders: { preset: "outside", style: "thin", color: "#93C5FD" },
};
const kpiLabelFormat = {
  fill: "#E5E7EB",
  font: { bold: true, color: "#374151" },
  horizontalAlignment: "center",
  borders: { preset: "outside", style: "thin", color: "#CBD5E1" },
};
const kpiValueFormat = {
  fill: "#F8FAFC",
  font: { bold: true, color: "#0F172A", size: 16 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "outside", style: "thin", color: "#CBD5E1" },
};
const noteFormat = {
  fill: "#FFF7ED",
  font: { color: "#9A3412" },
  wrapText: true,
  borders: { preset: "outside", style: "thin", color: "#FDBA74" },
};

for (const sheet of [
  dashboard, straits, ports, quality, config, runLog, dashboardData,
]) {
  sheet.showGridLines = false;
}

// Source and helper data for the interactive dashboard.
const unifiedRows = [...report.straits, ...report.ports]
  .sort((a, b) =>
    a.observation_date.localeCompare(b.observation_date) ||
    a.area_name.localeCompare(b.area_name)
  );
const dashboardDataHeaders = [
  "Date", "Area type", "Region", "Area", "Actual", "7-day average",
  "30-day average", "Bulk – O&G", "Bulk – non-O&G", "Container",
  "Other cargo", "Unknown",
];
const dashboardDataRows = unifiedRows.map((row) => [
  new Date(`${row.observation_date}T00:00:00Z`),
  row.area_type === "strait" ? "Strait" : "Port",
  row.region,
  row.area_name,
  row.total,
  row.avg_7d,
  row.avg_30d,
  row.bulk_og,
  row.bulk_non_og,
  row.container,
  row.other_cargo,
  row.unknown,
]);
dashboardData.getRange(`A1:L${dashboardDataRows.length + 1}`).values = [
  dashboardDataHeaders,
  ...dashboardDataRows,
];
dashboardData.getRange("A1:L1").format = headerFormat;
dashboardData.getRange(`A2:A${dashboardDataRows.length + 1}`).format.numberFormat = "yyyy-mm-dd";
dashboardData.getRange(`E2:L${dashboardDataRows.length + 1}`).format.numberFormat = "#,##0.0";
dashboardData.freezePanes.freezeRows(1);
dashboardData.getRange("A:A").format.columnWidth = 12;
dashboardData.getRange("B:C").format.columnWidth = 16;
dashboardData.getRange("D:D").format.columnWidth = 24;
dashboardData.getRange("E:L").format.columnWidth = 16;

const dates = [...new Set(unifiedRows.map((row) => row.observation_date))].sort();
dashboardData.getRange(`N1:R${dates.length + 1}`).values = [
  ["Date value", "Date", "Actual", "7-day average", "30-day average"],
  ...dates.map((item) => [
    new Date(`${item}T00:00:00Z`), item, null, null, null,
  ]),
];
dashboardData.getRange("N1:R1").format = headerFormat;
dashboardData.getRange(`N2:N${dates.length + 1}`).format.numberFormat = "yyyy-mm-dd";
dashboardData.getRange(`P2:R${dates.length + 1}`).format.numberFormat = "#,##0.0";

function selectorFormula(valueColumn, helperRow) {
  return `=IF(Dashboard!$B$6<>"All",` +
    `SUMIFS($${valueColumn}$2:$${valueColumn}$2000,$A$2:$A$2000,$N${helperRow},$D$2:$D$2000,Dashboard!$B$6),` +
    `IF(Dashboard!$B$5="All",` +
    `SUMIFS($${valueColumn}$2:$${valueColumn}$2000,$A$2:$A$2000,$N${helperRow},$B$2:$B$2000,Dashboard!$B$4),` +
    `SUMIFS($${valueColumn}$2:$${valueColumn}$2000,$A$2:$A$2000,$N${helperRow},$B$2:$B$2000,Dashboard!$B$4,$C$2:$C$2000,Dashboard!$B$5)))`;
}

for (let index = 0; index < dates.length; index += 1) {
  const row = index + 2;
  dashboardData.getRange(`P${row}:R${row}`).formulas = [[
    selectorFormula("E", row),
    selectorFormula("F", row),
    selectorFormula("G", row),
  ]];
}

// One-page analysis dashboard.
dashboard.getRange("A1:N2").merge();
dashboard.getRange("A1").values = [[report.metadata.title]];
dashboard.getRange("A1:N2").format = titleFormat;
dashboard.getRange("A4:A7").values = [
  ["Area type"],
  ["Region"],
  ["Specific area"],
  ["Observation date"],
];
dashboard.getRange("A4:A7").format = headerFormat;
dashboard.getRange("B4:B7").values = [
  ["Strait"],
  ["All"],
  ["All"],
  [new Date(`${report.metadata.target_date}T00:00:00Z`)],
];
dashboard.getRange("B4:B6").format = controlFormat;
dashboard.getRange("B7").format.numberFormat = "yyyy-mm-dd";
dashboard.getRange("B4").dataValidation = {
  rule: { type: "list", values: ["Strait", "Port"] },
};
const regions = ["All", ...new Set(report.areas.map((area) => area.region))].sort(
  (a, b) => (a === "All" ? -1 : b === "All" ? 1 : a.localeCompare(b))
);
dashboard.getRange("B5").dataValidation = {
  rule: { type: "list", values: regions },
};
const areaNames = ["All", ...report.areas.map((area) => area.name).sort()];
dashboard.getRange("B6").dataValidation = {
  rule: { type: "list", values: areaNames },
};
dashboard.getRange("A4:A7").format.columnWidth = 20;
dashboard.getRange("B:B").format.columnWidth = 24;

const lastHelperRow = dates.length + 1;
const kpis = [
  { label: "Actual activity", labelRange: "A9:B9", valueRange: "A10:B12", formula: `='Dashboard_Data'!P${lastHelperRow}`, format: "#,##0.0" },
  { label: "7-day average", labelRange: "C9:D9", valueRange: "C10:D12", formula: `='Dashboard_Data'!Q${lastHelperRow}`, format: "#,##0.0" },
  { label: "30-day average", labelRange: "E9:F9", valueRange: "E10:F12", formula: `='Dashboard_Data'!R${lastHelperRow}`, format: "#,##0.0" },
  { label: "Vs 7-day", labelRange: "A14:B14", valueRange: "A15:B17", formula: "=IFERROR(A10/C10-1,\"\")", format: "0.0%" },
  { label: "Vs 30-day", labelRange: "C14:D14", valueRange: "C15:D17", formula: "=IFERROR(A10/E10-1,\"\")", format: "0.0%" },
  { label: "Coverage", labelRange: "E14:F14", valueRange: "E15:F17", formula: '=IF(B6<>"All","Specific area",IF(B5<>"All",B5,B4))', format: "@" },
];
for (const item of kpis) {
  dashboard.getRange(item.labelRange).merge();
  dashboard.getRange(item.labelRange.split(":")[0]).values = [[item.label]];
  dashboard.getRange(item.labelRange).format = kpiLabelFormat;
  dashboard.getRange(item.valueRange).merge();
  dashboard.getRange(item.valueRange.split(":")[0]).formulas = [[item.formula]];
  dashboard.getRange(item.valueRange).format = kpiValueFormat;
  dashboard.getRange(item.valueRange).format.numberFormat = item.format;
}

dashboard.getRange("A19:F19").merge();
dashboard.getRange("A19").values = [["Current vessel-category mix"]];
dashboard.getRange("A19:F19").format = headerFormat;
dashboard.getRange("A20:B24").values = [
  ["Bulk – oil & gas", null],
  ["Bulk – non-oil & gas", null],
  ["Container", null],
  ["Other cargo", null],
  ["Unknown", null],
];
dashboard.getRange("A20:A24").format = { font: { bold: true, color: "#374151" } };
const categoryColumns = ["H", "I", "J", "K", "L"];
for (let index = 0; index < categoryColumns.length; index += 1) {
  const targetRow = index + 20;
  dashboard.getRange(`B${targetRow}`).formulas = [[
    `=IF($B$6<>"All",` +
    `SUMIFS('Dashboard_Data'!$${categoryColumns[index]}$2:$${categoryColumns[index]}$2000,'Dashboard_Data'!$A$2:$A$2000,$B$7,'Dashboard_Data'!$D$2:$D$2000,$B$6),` +
    `IF($B$5="All",` +
    `SUMIFS('Dashboard_Data'!$${categoryColumns[index]}$2:$${categoryColumns[index]}$2000,'Dashboard_Data'!$A$2:$A$2000,$B$7,'Dashboard_Data'!$B$2:$B$2000,$B$4),` +
    `SUMIFS('Dashboard_Data'!$${categoryColumns[index]}$2:$${categoryColumns[index]}$2000,'Dashboard_Data'!$A$2:$A$2000,$B$7,'Dashboard_Data'!$B$2:$B$2000,$B$4,'Dashboard_Data'!$C$2:$C$2000,$B$5)))`,
  ]];
  dashboard.getRange(`B${targetRow}`).format.numberFormat = "#,##0.0";
}
dashboard.getRange("A20:B24").format.borders = {
  preset: "outside", style: "thin", color: "#CBD5E1",
};
dashboard.getRange("A27:F29").merge();
dashboard.getRange("A27").values = [[
  "Specific area overrides the Area type and Region controls. PortWatch is aggregate daily activity; exact parked-vessel counts require licensed vessel-level AIS."
]];
dashboard.getRange("A27:F29").format = noteFormat;
dashboard.getRange("A31:F31").values = [[
  "Snapshot schedule", `${report.metadata.snapshot_time} ${report.metadata.timezone}`,
  "Generated", new Date(report.metadata.generated_at), "Source", "IMF PortWatch",
]];
dashboard.getRange("A31:F31").format = { font: { color: "#64748B", size: 9 } };
dashboard.getRange("D31").format.numberFormat = "yyyy-mm-dd hh:mm:ss";
dashboard.freezePanes.freezeRows(3);
workbook.comments.addThread(
  { cell: dashboard.getRange("B6") },
  "Choose All to use the Area type and Region filters. Choosing a specific area overrides those broader filters."
);

const trendChart = dashboard.charts.add(
  "line",
  dashboardData.getRange(`O1:R${dates.length + 1}`),
);
trendChart.title = "Actual traffic vs rolling averages";
trendChart.hasLegend = true;
trendChart.xAxis = { axisType: "textAxis", textStyle: { fontSize: 9 } };
trendChart.yAxis = { numberFormatCode: "#,##0", title: { text: "Daily activity" } };
trendChart.setPosition("H4", "N20");

// Detailed source tabs.
const straitHeaders = [
  "Date", "Area ID", "Strait", "Region", "Total crossings", "Bulk – O&G",
  "Bulk – non-O&G", "Container", "Other cargo", "Others", "Unknown",
  "7d avg", "30d avg", "Change vs 7d", "Change vs 30d", "Availability",
  "Source", "Source URL",
];
const portHeaders = [
  "Date", "Area ID", "Port", "Region", "Total activity", "Bulk – O&G",
  "Bulk – non-O&G", "Container", "Other cargo", "Others", "Unknown",
  "Imports (t)", "Exports (t)", "7d avg", "30d avg", "Change vs 7d",
  "Change vs 30d", "Availability", "Source", "Source URL",
];
const straitRows = report.straits.map((row) => [
  new Date(`${row.observation_date}T00:00:00Z`), row.area_id, row.area_name, row.region,
  row.total, row.bulk_og, row.bulk_non_og, row.container, row.other_cargo, row.others,
  row.unknown, row.avg_7d, row.avg_30d, row.change_7d, row.change_30d,
  row.availability, row.source, row.source_url,
]);
const portRows = report.ports.map((row) => [
  new Date(`${row.observation_date}T00:00:00Z`), row.area_id, row.area_name, row.region,
  row.total, row.bulk_og, row.bulk_non_og, row.container, row.other_cargo, row.others,
  row.unknown, row.imports_tons, row.exports_tons, row.avg_7d, row.avg_30d,
  row.change_7d, row.change_30d, row.availability, row.source, row.source_url,
]);
straits.getRange(`A1:R${straitRows.length + 1}`).values = [straitHeaders, ...straitRows];
ports.getRange(`A1:T${portRows.length + 1}`).values = [portHeaders, ...portRows];

for (const [sheet, rowCount, lastColumn, tableName] of [
  [straits, straitRows.length, "R", "DailyStraitTraffic"],
  [ports, portRows.length, "T", "DailyPortActivity"],
]) {
  sheet.getRange(`A1:${lastColumn}1`).format = headerFormat;
  sheet.getRange(`A2:A${rowCount + 1}`).format.numberFormat = "yyyy-mm-dd";
  sheet.getRange(`E2:O${rowCount + 1}`).format.numberFormat = "#,##0.0";
  sheet.getRange(`N2:O${rowCount + 1}`).format.numberFormat = "0.0%";
  if (sheet === ports) {
    sheet.getRange(`P2:Q${rowCount + 1}`).format.numberFormat = "0.0%";
  }
  sheet.getRange("A:A").format.columnWidth = 12;
  sheet.getRange("B:B").format.columnWidth = 20;
  sheet.getRange("C:C").format.columnWidth = 23;
  sheet.getRange("D:D").format.columnWidth = 16;
  sheet.getRange(`E:${lastColumn}`).format.columnWidth = 14;
  sheet.getRange(`${lastColumn}:${lastColumn}`).format.columnWidth = 34;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(4);
  const table = sheet.tables.add(`A1:${lastColumn}${rowCount + 1}`, true, tableName);
  table.style = "TableStyleLight1";
}

quality.getRange(`A1:D${report.quality.length + 1}`).values = [
  ["Check", "Status", "Value", "Detail"],
  ...report.quality.map((row) => [row.check, row.status, row.value, row.detail]),
];
quality.getRange("A1:D1").format = headerFormat;
quality.getRange("A:A").format.columnWidth = 30;
quality.getRange("B:B").format.columnWidth = 16;
quality.getRange("C:C").format.columnWidth = 15;
quality.getRange("D:D").format.columnWidth = 65;
quality.getRange(`B2:B${report.quality.length + 1}`).conditionalFormats.add(
  "containsText", { text: "WARN", format: { fill: "#FEF3C7", font: { color: "#92400E" } } }
);
quality.getRange(`B2:B${report.quality.length + 1}`).conditionalFormats.add(
  "containsText", { text: "FAIL", format: { fill: "#FEE2E2", font: { color: "#991B1B" } } }
);
quality.freezePanes.freezeRows(1);

config.getRange(`A1:G${report.areas.length + 1}`).values = [
  ["Area ID", "Name", "Source name", "Type", "Region", "Latitude", "Longitude"],
  ...report.areas.map((area) => [
    area.id, area.name, area.source_name, area.type, area.region, area.lat, area.lon,
  ]),
];
config.getRange("A1:G1").format = headerFormat;
config.getRange("A:C").format.columnWidth = 24;
config.getRange("D:E").format.columnWidth = 16;
config.getRange("F:G").format.columnWidth = 14;
config.freezePanes.freezeRows(1);

const runHeaders = [
  "Run ID", "Started at", "Completed at", "Status", "Provider", "Target date",
  "Rows", "Warnings", "Message",
];
runLog.getRange(`A1:I${report.runs.length + 1}`).values = [
  runHeaders,
  ...report.runs.map((run) => [
    run.run_id,
    run.started_at ? new Date(run.started_at) : null,
    run.completed_at ? new Date(run.completed_at) : null,
    run.status,
    run.provider,
    new Date(`${run.target_date}T00:00:00Z`),
    run.row_count,
    run.warning_count,
    run.message,
  ]),
];
runLog.getRange("A1:I1").format = headerFormat;
runLog.getRange(`B2:C${report.runs.length + 1}`).format.numberFormat = "yyyy-mm-dd hh:mm:ss";
runLog.getRange(`F2:F${report.runs.length + 1}`).format.numberFormat = "yyyy-mm-dd";
runLog.getRange("A:A").format.columnWidth = 38;
runLog.getRange("B:C").format.columnWidth = 25;
runLog.getRange("D:I").format.columnWidth = 16;
runLog.getRange("I:I").format.columnWidth = 30;
runLog.freezePanes.freezeRows(1);

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
const inspect = await workbook.inspect({
  kind: "sheet,table,drawing",
  maxChars: 10000,
  tableMaxRows: 4,
  tableMaxCols: 10,
});
await fs.writeFile(path.join(previewDir, "inspection.ndjson"), inspect.ndjson, "utf8");
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
await fs.writeFile(path.join(previewDir, "formula-errors.ndjson"), formulaErrors.ndjson, "utf8");

const previewRanges = {
  Dashboard: "A1:N31",
  Daily_Strait_Traffic: "A1:R40",
  Daily_Port_Activity: "A1:T40",
  Data_Quality: `A1:D${report.quality.length + 1}`,
  Area_Config: `A1:G${report.areas.length + 1}`,
  Run_Log: `A1:I${report.runs.length + 1}`,
  Dashboard_Data: "A1:R50",
};
for (const [sheetName, range] of Object.entries(previewRanges)) {
  const preview = await workbook.render({
    sheetName,
    range,
    scale: 1,
    format: "png",
  });
  await fs.writeFile(
    path.join(previewDir, `${sheetName}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

dashboard.getRange("B4:B6").values = [["Port"], ["Asia"], ["All"]];
const filteredCheck = await workbook.inspect({
  kind: "table",
  sheetId: "Dashboard",
  range: "A4:F24",
  include: "values,formulas",
  tableMaxRows: 24,
  tableMaxCols: 6,
  maxChars: 6000,
});
await fs.writeFile(
  path.join(previewDir, "filtered-port-asia-check.ndjson"),
  filteredCheck.ndjson,
  "utf8",
);
const filteredPreview = await workbook.render({
  sheetName: "Dashboard",
  range: "A1:N31",
  scale: 1,
  format: "png",
});
await fs.writeFile(
  path.join(previewDir, "Dashboard_Filtered_Port_Asia.png"),
  new Uint8Array(await filteredPreview.arrayBuffer()),
);
dashboard.getRange("B4:B6").values = [["Strait"], ["All"], ["All"]];

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
