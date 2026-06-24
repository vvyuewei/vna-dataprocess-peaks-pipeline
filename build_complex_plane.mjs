import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const inputPath = "D:/005 不同项目文章/001 不同扫描的远距离 微弱信号恢复/000 excel数据/传输0622/s001 11_complex_wide.csv";
const outputDir = "D:/codex-data process/outputs/complex_plane_s001";
const outputPath = `${outputDir}/s001_11_complex_plane.xlsx`;
const previewPath = `${outputDir}/s001_11_complex_plane_preview.png`;

const csvText = await fs.readFile(inputPath, "utf8");
const workbook = await Workbook.fromCSV(csvText, { sheetName: "Raw Data" });
const raw = workbook.worksheets.getItem("Raw Data");
const lines = csvText.trim().split(/\r?\n/);
const rowCount = lines.length - 1;
const lastRow = rowCount + 1;

raw.freezePanes.freezeRows(1);
raw.showGridLines = false;
raw.getRange("A1:I1").format = {
  fill: "#17365D",
  font: { bold: true, color: "#FFFFFF" },
  wrapText: true,
};
raw.getRange(`A2:A${lastRow}`).format.numberFormat = "0.000";
raw.getRange(`B2:I${lastRow}`).format.numberFormat = "0.000000";
raw.getRange("A:I").format.columnWidth = 22;

const plot = workbook.worksheets.add("Complex Plane");
plot.showGridLines = false;
plot.getRange("A1:E1").merge();
plot.getRange("A1").values = [["s001 11 — 复平面轨迹"]];
plot.getRange("A1:E1").format = {
  fill: "#17365D",
  font: { bold: true, color: "#FFFFFF", size: 16 },
  verticalAlignment: "center",
};
plot.getRange("A1:E1").format.rowHeight = 28;
plot.getRange("A2:E2").merge();
plot.getRange("A2").values = [["横轴：实部 Re(z)；纵轴：虚部 Im(z)。两条轨迹按原始频率顺序排列。"]];
plot.getRange("A2:E2").format = { font: { color: "#44546A", italic: true } };

plot.getRange("A4:E4").values = [["Frequency_MHz", "Re curve002", "Im curve002", "Re curve001", "Im curve001"]];
plot.getRange("A4:E4").format = {
  fill: "#D9EAF7",
  font: { bold: true, color: "#17365D" },
  borders: { preset: "all", style: "thin", color: "#A6B8C8" },
};
plot.getRange("A5:E5").formulas = [["='Raw Data'!A2", "='Raw Data'!B2", "='Raw Data'!C2", "='Raw Data'!F2", "='Raw Data'!G2"]];
plot.getRange(`A5:E${rowCount + 4}`).fillDown();
plot.getRange(`A5:A${rowCount + 4}`).format.numberFormat = "0.000";
plot.getRange(`B5:E${rowCount + 4}`).format.numberFormat = "0.000000";
plot.getRange("A:E").format.columnWidth = 16;
plot.freezePanes.freezeRows(4);

const detail = plot.charts.add("scatter", {
  chartType: "scatter",
  title: "复平面轨迹（局部放大）",
  hasLegend: true,
});
const s2 = detail.series.add("curve002");
s2.categoryFormula = `'Complex Plane'!$B$5:$B$${rowCount + 4}`;
s2.formula = `'Complex Plane'!$C$5:$C$${rowCount + 4}`;
s2.fill = "#ED7D31";
const s1 = detail.series.add("curve001");
s1.categoryFormula = `'Complex Plane'!$D$5:$D$${rowCount + 4}`;
s1.formula = `'Complex Plane'!$E$5:$E$${rowCount + 4}`;
s1.fill = "#4472C4";
detail.title = "复平面轨迹（局部放大）";
detail.hasLegend = true;
detail.xAxis = { min: 0.68, max: 1.03, numberFormatCode: "0.00" };
detail.yAxis = { min: -0.065, max: 0.285, numberFormatCode: "0.00" };
detail.xAxis.title.text = "实部 Re(z)";
detail.yAxis.title.text = "虚部 Im(z)";
detail.setPosition("G2", "P34");

plot.getRange("G35:P36").merge();
plot.getRange("G35").values = [["注：主图采用等跨度坐标范围（横、纵轴均为 0.35），便于保持复平面几何比例。"]];
plot.getRange("G35:P36").format = {
  fill: "#FFF2CC",
  font: { color: "#7F6000", italic: true },
  wrapText: true,
};

await fs.mkdir(outputDir, { recursive: true });
const preview = await workbook.render({ sheetName: "Complex Plane", range: "A1:P36", scale: 1.2, format: "png" });
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
const check = await workbook.inspect({ kind: "table", range: "Complex Plane!A1:E10", include: "values,formulas", tableMaxRows: 10, tableMaxCols: 5 });
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 50 }, summary: "formula error scan" });
console.log(check.ndjson);
console.log(errors.ndjson);
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
console.log(JSON.stringify({ outputPath, previewPath, rowCount }));
