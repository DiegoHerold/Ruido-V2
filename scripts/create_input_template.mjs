import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const outputDir = `${root}/examples`;
const previewDir = `${root}/.tmp-preview`;
await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const workbook = Workbook.create();
const input = workbook.worksheets.add("Entrada");
input.showGridLines = false;
input.getRange("A1:I2").values = [
  ["CNPJ", "Perfil", "CPF", "Colaborador", "Agente Nocivo", "Intensidade", "Ano", "LOG", "Status"],
  [null, null, null, null, "02.01.001 - Ruído", null, null, null, null],
];
input.getRange("A1:I1").format = {
  fill: "#1F4E78",
  font: { name: "Arial", bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "all", style: "thin", color: "#FFFFFF" },
};
input.getRange("A2:I2").format = { fill: "#FFF2CC", font: { name: "Arial", color: "#1F1F1F" } };
input.getRange("A:A").format.numberFormat = "@";
input.getRange("C:C").format.numberFormat = "@";
input.getRange("F:F").format.numberFormat = "0.00";
input.getRange("G:G").format.numberFormat = "dd/mm/yyyy";
input.getRange("A:A").format.columnWidth = 20;
input.getRange("B:B").format.columnWidth = 18;
input.getRange("C:C").format.columnWidth = 16;
input.getRange("D:D").format.columnWidth = 34;
input.getRange("E:E").format.columnWidth = 24;
input.getRange("F:G").format.columnWidth = 16;
input.getRange("H:H").format.columnWidth = 30;
input.getRange("I:I").format.columnWidth = 16;
input.getRange("A1:I2").format.rowHeight = 22;
input.freezePanes.freezeRows(1);

const instructions = workbook.worksheets.add("Instruções");
instructions.showGridLines = false;
instructions.getRange("A1:B10").values = [
  ["Campo", "Orientação"],
  ["CNPJ", "Obrigatório para Perfil Pessoa Jurídica. Informe 14 dígitos."],
  ["Perfil", "Obrigatório. Informe Pessoa Jurídica ou Pessoa Física."],
  ["CPF", "Obrigatório. Informe 11 dígitos; mantenha a coluna como texto para preservar zeros à esquerda."],
  ["Colaborador", "Opcional. Usado somente para conferência visual do trabalhador encontrado."],
  ["Agente Nocivo", "Informativo. A automação consulta sempre 02.01.001 - Ruído."],
  ["Intensidade", "Obrigatório. Valor esperado para comparar com o eSocial."],
  ["Ano", "Obrigatório. Data de início da exposição em dd/mm/aaaa."],
  ["LOG", "Opcional. Campo livre para observações de origem; a automação mantém a evidência própria."],
  ["Status", "Deixe em branco para consultar. A automação escreve Concluido ao finalizar a linha; linhas já concluídas são ignoradas."],
];
instructions.getRange("A1:B1").format = { fill: "#1F4E78", font: { name: "Arial", bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
instructions.getRange("A2:A10").format = { font: { name: "Arial", bold: true }, fill: "#D9EAF7" };
instructions.getRange("B2:B10").format = { font: { name: "Arial" }, wrapText: true, verticalAlignment: "top" };
instructions.getRange("A:A").format.columnWidth = 20;
instructions.getRange("B:B").format.columnWidth = 85;
instructions.getRange("A1:B10").format.rowHeight = 28;

const check = await workbook.inspect({ kind: "table", range: "Entrada!A1:I2", include: "values,formulas", tableMaxRows: 3, tableMaxCols: 9 });
if (!check) throw new Error("Não foi possível inspecionar o template de entrada.");
const preview = await workbook.render({ sheetName: "Entrada", range: "A1:I5", scale: 2, format: "png" });
await fs.writeFile(`${previewDir}/input-template.png`, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(`${outputDir}/input-template.xlsx`);
