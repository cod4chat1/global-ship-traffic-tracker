function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("Shipping Map")
    .addItem("Open world map", "showShippingMap")
    .addToUi();
}

function showShippingMap() {
  const html = HtmlService.createHtmlOutputFromFile("ShippingMap")
    .setWidth(1200)
    .setHeight(760);
  SpreadsheetApp.getUi().showModalDialog(html, "Global Shipping Activity Map");
}

function getShippingMapData() {
  const workbook = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = workbook.getSheetByName("Map_Data");
  if (!sheet) {
    throw new Error("Map_Data is missing. Run the ship-traffic updater first.");
  }
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) {
    throw new Error("Map_Data is empty. Run the ship-traffic updater first.");
  }
  const headers = values[0].map(String);
  return values.slice(1).map(function (row) {
    const item = {};
    headers.forEach(function (header, index) {
      const value = row[index];
      item[header] = value instanceof Date
        ? Utilities.formatDate(value, "UTC", "yyyy-MM-dd")
        : value;
    });
    return item;
  });
}
