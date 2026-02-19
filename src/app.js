/**
 * UI logic for ADB SQLite Query Viewer (WebUSB edition).
 * Replaces all fetch('/api/...') calls with adbClient methods.
 */
import { AdbClient } from "./adb-client.js";

const adbClient = new AdbClient();

// ──────────────── State ────────────────
let currentTable = null;
let currentOffset = 0;
let currentLimit = 100;
let totalCount = 0;
let activeTab = "query";
let dbSearchTimeout = null;
let allPackages = [];
let selectedPackageName = "";

// ──────────────── DOM references ────────────────
const $ = (id) => document.getElementById(id);

// ──────────────── Init ────────────────
window.addEventListener("DOMContentLoaded", () => {
  // Restore saved query
  const savedQuery = localStorage.getItem("sqliteViewerQuery");
  if (savedQuery) $("queryInput").value = savedQuery;

  // Restore config collapse state
  if (localStorage.getItem("sqliteViewerConfigCollapsed") === "true") {
    $("configSection").classList.remove("expanded");
  }

  // Auto-save query
  $("queryInput").addEventListener("input", (e) => {
    localStorage.setItem("sqliteViewerQuery", e.target.value);
  });

  // F5 = execute
  document.addEventListener("keydown", (e) => {
    if (e.key === "F5") {
      e.preventDefault();
      executeQuery();
    }
  });

  // Table search
  $("tableSearch").addEventListener("input", (e) => filterTables(e.target.value));

  // Close dropdowns on outside click
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#searchResultsDropdown") && !e.target.closest("#dbSearchInput")) {
      $("searchResultsDropdown").classList.remove("visible");
    }
    if (!e.target.closest("#packageDropdown") && !e.target.closest("#packageSearchInput")) {
      $("packageDropdown").classList.remove("visible");
    }
  });

  // ── Wire up buttons ──
  $("configToggleBtn").addEventListener("click", toggleConfig);
  $("usbConnectBtn").addEventListener("click", onUsbConnectClick);
  $("packageSearchInput").addEventListener("focus", showPackageDropdown);
  $("packageSearchInput").addEventListener("input", filterPackageDropdown);
  $("packageClearBtn").addEventListener("click", (e) => clearPackageSelection(e));
  $("databaseSelect").addEventListener("change", () => onDatabaseChange());
  $("dbSearchInput").addEventListener("input", onDbSearchInput);
  $("dbSearchInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") searchDatabases();
  });
  $("dbSearchBtn").addEventListener("click", searchDatabases);
  $("executeBtn").addEventListener("click", () => executeQuery());
  $("executeAllBtn").addEventListener("click", executeAllQuery);
  $("refreshTablesBtn").addEventListener("click", refreshTables);
  $("clearQueryBtn").addEventListener("click", clearQuery);
  $("formatQueryBtn").addEventListener("click", formatQuery);
  $("firstBtn").addEventListener("click", firstPage);
  $("prevBtn").addEventListener("click", previousPage);
  $("nextBtn").addEventListener("click", nextPage);
  $("lastBtn").addEventListener("click", lastPage);
  $("gotoPageBtn").addEventListener("click", gotoPage);
  $("gotoPageInput").addEventListener("keypress", (e) => {
    if (e.key === "Enter") gotoPage();
  });
  $("limitSelect").addEventListener("change", changeLimit);

  // Tabs
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });

  // Try bridge first, then fall back to WebUSB auto-reconnect
  tryBridgeThenAutoReconnect();
});

// ──────────────── Bridge + USB Connection ────────────────

async function tryBridgeThenAutoReconnect() {
  try {
    const bridgeFound = await adbClient.connectBridge();
    if (bridgeFound) {
      showBridgeConnected();
      await loadBridgeDevices();
      return;
    }
  } catch {
    /* bridge not available */
  }
  // Fall back to WebUSB
  await tryAutoReconnect();
}

function showBridgeConnected() {
  const statusEl = $("connectionStatus");
  statusEl.textContent = "ADB Bridge";
  statusEl.className = "connection-status bridge";
  $("deviceStatus").textContent = "Bridge connected on :15555";
  $("deviceStatus").classList.add("ok");

  const btn = $("usbConnectBtn");
  btn.textContent = "Disconnect Bridge";
  btn.classList.add("disconnect");
}

async function loadBridgeDevices() {
  try {
    const devices = await adbClient.getDevices();
    if (devices.length === 0) {
      $("deviceStatus").textContent = "Bridge connected — no devices found. Plug in a phone.";
      $("deviceStatus").classList.remove("ok");
      return;
    }

    if (devices.length === 1) {
      // Auto-select the only device
      adbClient.bridgeSerial = devices[0].serial;
      $("deviceStatus").textContent = devices[0].display_name;
      $("deviceStatus").classList.add("ok");
      await loadPackages();
      return;
    }

    // Multiple devices — let user pick
    adbClient.bridgeSerial = devices[0].serial;
    $("deviceStatus").textContent = devices[0].display_name;
    $("deviceStatus").classList.add("ok");
    await loadPackages();
  } catch (err) {
    $("deviceStatus").textContent = `Bridge error: ${err.message}`;
    $("deviceStatus").classList.remove("ok");
  }
}

async function tryAutoReconnect() {
  try {
    const devices = await adbClient.getDevices();
    const savedSerial = localStorage.getItem("sqliteViewerDevice");
    if (devices.length === 1) {
      $("deviceStatus").textContent = "Reconnecting...";
      await adbClient.connectBySerial(devices[0].serial);
      await onDeviceConnected();
    } else if (savedSerial) {
      const match = devices.find((d) => d.serial === savedSerial);
      if (match) {
        $("deviceStatus").textContent = "Reconnecting...";
        await adbClient.connectBySerial(savedSerial);
        await onDeviceConnected();
      }
    }
  } catch {
    /* no previously paired device or connection failed */
  }
}

async function onUsbConnectClick() {
  const btn = $("usbConnectBtn");

  if (adbClient.mode === "bridge" || adbClient.adb) {
    // Already connected → disconnect
    await adbClient.disconnect();
    btn.textContent = "Connect Device";
    btn.classList.remove("disconnect");
    $("deviceStatus").textContent = "No device connected";
    $("deviceStatus").classList.remove("ok");
    $("connectionStatus").textContent = "Disconnected";
    $("connectionStatus").className = "connection-status disconnected";
    $("packageSearchInput").disabled = true;
    $("packageSearchInput").placeholder = "Connect device first...";
    $("databaseSelect").disabled = true;
    $("tablesList").innerHTML =
      '<div class="info" style="margin: 10px; font-size: 12px;">Connect a USB device to get started.</div>';
    return;
  }

  btn.textContent = "Connecting...";
  $("deviceStatus").textContent = "Check your phone — approve USB debugging if prompted";
  try {
    await adbClient.requestDevice();
    await onDeviceConnected();
  } catch (err) {
    btn.textContent = "Connect Device";
    $("deviceStatus").textContent = `Error: ${err.message}`;
    $("deviceStatus").classList.remove("ok");
  }
}

async function onDeviceConnected() {
  const info = adbClient.getDeviceInfo();
  const btn = $("usbConnectBtn");
  btn.textContent = "Disconnect";
  btn.classList.add("disconnect");
  $("deviceStatus").textContent = info.display_name;
  $("deviceStatus").classList.add("ok");
  $("connectionStatus").textContent = "Connected";
  $("connectionStatus").className = "connection-status connected";

  localStorage.setItem("sqliteViewerDevice", info.serial);

  // Cascade: load packages
  await loadPackages();
}

// ──────────────── Configuration Panel ────────────────

function toggleConfig() {
  const section = $("configSection");
  section.classList.toggle("expanded");
  localStorage.setItem("sqliteViewerConfigCollapsed", !section.classList.contains("expanded"));
}

// ──────────────── Packages ────────────────

async function loadPackages() {
  const input = $("packageSearchInput");
  const wrapper = $("packageComboWrapper");
  input.disabled = false;
  input.placeholder = "Scanning debuggable apps...";
  input.value = "";
  wrapper.classList.remove("has-value");
  selectedPackageName = "";
  allPackages = [];

  try {
    allPackages = await adbClient.getPackages();
    input.placeholder = `Search ${allPackages.length} debuggable apps...`;

    // Restore saved package
    const savedPackage = localStorage.getItem("sqliteViewerPackage");
    if (savedPackage && allPackages.includes(savedPackage)) {
      selectedPackageName = savedPackage;
      input.value = savedPackage;
      wrapper.classList.add("has-value");
    }

    await onPackageChange(true);
  } catch (err) {
    input.placeholder = `Failed: ${err.message}`;
  }
}

function showPackageDropdown() {
  const input = $("packageSearchInput");
  if (selectedPackageName && input.value === selectedPackageName) {
    input.select();
  }
  filterPackageDropdown();
}

function filterPackageDropdown() {
  const input = $("packageSearchInput");
  const dropdown = $("packageDropdown");
  const query = input.value.trim().toLowerCase();

  const filtered = query
    ? allPackages.filter((pkg) => pkg.toLowerCase().includes(query))
    : allPackages;

  if (filtered.length === 0) {
    dropdown.innerHTML = '<div class="combo-empty">No matching packages</div>';
  } else {
    dropdown.innerHTML = filtered
      .map(
        (pkg) =>
          `<div class="combo-item${pkg === selectedPackageName ? " active" : ""}" data-pkg="${pkg}">${pkg}</div>`
      )
      .join("");
    // Attach click handlers
    dropdown.querySelectorAll(".combo-item").forEach((el) => {
      el.addEventListener("click", () => selectPackage(el.dataset.pkg));
    });
  }
  dropdown.classList.add("visible");
}

async function selectPackage(packageName) {
  const input = $("packageSearchInput");
  const wrapper = $("packageComboWrapper");
  const dropdown = $("packageDropdown");

  selectedPackageName = packageName;
  input.value = packageName;
  wrapper.classList.add("has-value");
  dropdown.classList.remove("visible");

  await onPackageChange();
}

async function clearPackageSelection(event) {
  if (event) event.stopPropagation();
  const input = $("packageSearchInput");
  const wrapper = $("packageComboWrapper");

  selectedPackageName = "";
  input.value = "";
  wrapper.classList.remove("has-value");
  input.focus();
  filterPackageDropdown();

  $("databaseSelect").innerHTML = '<option value="">Select a package first</option>';
  $("databaseSelect").disabled = true;
  localStorage.removeItem("sqliteViewerPackage");
}

async function onPackageChange(isInit = false) {
  if (!selectedPackageName) {
    $("databaseSelect").innerHTML = '<option value="">Select a package first</option>';
    $("databaseSelect").disabled = true;
    return;
  }

  localStorage.setItem("sqliteViewerPackage", selectedPackageName);
  adbClient.setPackage(selectedPackageName);
  await loadDatabases(isInit);
}

// ──────────────── Databases ────────────────

async function loadDatabases(isInit = false) {
  const select = $("databaseSelect");
  select.disabled = false;
  select.innerHTML = '<option value="">Loading databases...</option>';

  try {
    const databases = await adbClient.getDatabases(selectedPackageName);
    const savedDb = localStorage.getItem("sqliteViewerDatabase");
    select.innerHTML = '<option value="">-- Select database --</option>';

    databases.forEach((db) => {
      const option = document.createElement("option");
      option.value = db.name;
      option.textContent = `${db.name} (${db.path})`;
      option.dataset.path = db.path;
      if (savedDb && db.name === savedDb) option.selected = true;
      select.appendChild(option);
    });

    await onDatabaseChange(isInit);
  } catch (err) {
    select.innerHTML = `<option value="">Error: ${err.message}</option>`;
  }
}

async function onDatabaseChange(isInit = false) {
  const select = $("databaseSelect");
  const dbName = select.value;

  if (!dbName) {
    if (!isInit) {
      $("tablesList").innerHTML = '<div class="info" style="margin: 10px; font-size: 12px;">Select a database to view tables</div>';
    }
    return;
  }

  // Get path from selected option
  const selectedOption = select.options[select.selectedIndex];
  const dbPath = selectedOption?.dataset?.path || "";

  localStorage.setItem("sqliteViewerDatabase", dbName);
  adbClient.setDatabase(dbName, dbPath);

  await updateConnectionStatus();
  await loadTables();
}

// ──────────────── Database Search ────────────────

function onDbSearchInput() {
  clearTimeout(dbSearchTimeout);
  const query = $("dbSearchInput").value.trim();
  if (query.length < 1) {
    $("searchResultsDropdown").classList.remove("visible");
    return;
  }
  dbSearchTimeout = setTimeout(() => searchDatabases(), 400);
}

async function searchDatabases() {
  const query = $("dbSearchInput").value.trim();
  const dropdown = $("searchResultsDropdown");

  if (!selectedPackageName) {
    dropdown.innerHTML = '<div class="search-result-item"><span class="file-name">Select a package first</span></div>';
    dropdown.classList.add("visible");
    return;
  }
  if (!query) {
    dropdown.classList.remove("visible");
    return;
  }

  dropdown.innerHTML = '<div class="search-result-item"><span class="file-name">Searching...</span></div>';
  dropdown.classList.add("visible");

  try {
    const databases = await adbClient.searchDatabases(selectedPackageName, query);

    if (databases.length === 0) {
      dropdown.innerHTML = '<div class="search-result-item"><span class="file-name">No databases found</span></div>';
      return;
    }

    dropdown.innerHTML = databases
      .map(
        (db) =>
          `<div class="search-result-item" data-name="${db.name}" data-path="${db.path}">
            <div class="file-name">${db.name}</div>
            <div class="file-path">${db.path}</div>
          </div>`
      )
      .join("");

    dropdown.querySelectorAll(".search-result-item").forEach((el) => {
      el.addEventListener("click", () => selectSearchResult(el.dataset.name, el.dataset.path));
    });
  } catch (err) {
    dropdown.innerHTML = `<div class="search-result-item"><span class="file-name">Search failed: ${err.message}</span></div>`;
  }
}

async function selectSearchResult(dbName, dbPath) {
  $("searchResultsDropdown").classList.remove("visible");
  $("dbSearchInput").value = "";

  const select = $("databaseSelect");
  let found = false;
  for (let i = 0; i < select.options.length; i++) {
    if (select.options[i].value === dbName) {
      select.value = dbName;
      found = true;
      break;
    }
  }
  if (!found) {
    const option = document.createElement("option");
    option.value = dbName;
    option.textContent = `${dbName} (${dbPath})`;
    option.dataset.path = dbPath;
    select.appendChild(option);
    select.value = dbName;
  }

  await onDatabaseChange();
}

// ──────────────── Connection Status ────────────────

async function updateConnectionStatus() {
  const statusEl = $("connectionStatus");
  const isConnected = adbClient.mode === "bridge" ? !!adbClient.bridgeUrl : !!adbClient.adb;
  if (!isConnected) {
    statusEl.textContent = "Disconnected";
    statusEl.className = "connection-status disconnected";
    return;
  }

  try {
    const exists = await adbClient.checkDatabaseExists();
    if (exists) {
      statusEl.textContent = adbClient.mode === "bridge" ? "ADB Bridge" : "Connected";
      statusEl.className = adbClient.mode === "bridge" ? "connection-status bridge" : "connection-status connected";
    } else {
      statusEl.textContent = "DB not found";
      statusEl.className = "connection-status disconnected";
    }
  } catch {
    statusEl.textContent = adbClient.mode === "bridge" ? "ADB Bridge" : "Connected";
    statusEl.className = adbClient.mode === "bridge" ? "connection-status bridge" : "connection-status connected";
  }
}

// ──────────────── Tables ────────────────

async function loadTables() {
  const tablesList = $("tablesList");
  tablesList.innerHTML = '<div class="loading">Loading tables...</div>';

  try {
    const tables = await adbClient.getTables();

    if (tables.length === 0) {
      tablesList.innerHTML = '<div class="info" style="margin: 10px; font-size: 12px;">No tables found</div>';
      return;
    }

    tablesList.innerHTML = tables
      .map(
        (table) => `
        <div class="table-item" data-table="${table.name}">
          <div class="accordion-header">
            <span class="arrow">&#9654;</span>
            <div class="table-item-name">${table.name}</div>
            <button class="query-btn" data-select-table="${table.name}">Query</button>
          </div>
          <div class="accordion-content" id="structure-${table.name}">
            <div style="color: #95a5a6; font-style: italic;">Loading columns...</div>
          </div>
        </div>`
      )
      .join("");

    // Attach handlers
    tablesList.querySelectorAll(".accordion-header").forEach((header) => {
      header.addEventListener("click", (e) => {
        if (e.target.classList.contains("query-btn")) return;
        const name = header.closest(".table-item").dataset.table;
        toggleAccordion(header, name);
      });
    });

    tablesList.querySelectorAll(".query-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        selectTable(btn.dataset.selectTable);
      });
    });
  } catch (err) {
    tablesList.innerHTML = `<div class="error" style="margin: 10px; font-size: 12px;">Failed to load tables: ${err.message}</div>`;
  }
}

function filterTables(searchText) {
  const items = document.querySelectorAll(".table-item");
  const search = searchText.toLowerCase();
  items.forEach((item) => {
    const tableName = item.dataset.table.toLowerCase();
    item.style.display = tableName.includes(search) ? "block" : "none";
  });
}

async function selectTable(tableName) {
  currentTable = tableName;
  currentOffset = 0;

  document.querySelectorAll(".table-item").forEach((item) => {
    const header = item.querySelector(".accordion-header");
    const isActive = item.dataset.table === tableName;
    item.style.borderLeftColor = isActive ? "#3498db" : "transparent";
    header.style.background = isActive ? "#34495e" : "";
  });

  const queryInput = $("queryInput");
  const existingQuery = queryInput.value.trim();
  const newQuery = `SELECT * FROM ${tableName}`;
  queryInput.value = existingQuery ? existingQuery + "\n\n" + newQuery : newQuery;
  localStorage.setItem("sqliteViewerQuery", queryInput.value);

  if (activeTab === "query") {
    await loadTableData(tableName);
  } else {
    await loadTableStructure(tableName);
  }
}

async function toggleAccordion(element, tableName) {
  const tableItem = element.closest(".table-item");
  const content = tableItem.querySelector(".accordion-content");
  const wasExpanded = tableItem.classList.contains("expanded");
  tableItem.classList.toggle("expanded");

  if (!wasExpanded && !content.dataset.loaded) {
    await loadSidebarStructure(tableName, content);
  }
}

async function loadSidebarStructure(tableName, container) {
  try {
    const columns = await adbClient.getTableStructure(tableName);
    container.dataset.loaded = "true";

    if (!columns || columns.length === 0) {
      container.innerHTML = '<div style="color: #95a5a6">No columns</div>';
      return;
    }

    container.innerHTML = columns
      .map(
        (col) => `
        <div class="column-item">
          <span>${col.pk ? '<span class="pk-badge" title="Primary Key">PK</span>' : ""}${col.name}</span>
          <span class="column-type">${col.type}</span>
        </div>`
      )
      .join("");
  } catch (err) {
    container.innerHTML = `<div style="color: #e74c3c">Error: ${err.message}</div>`;
  }
}

// ──────────────── Table Data / Query ────────────────

async function loadTableData(tableName, offset = 0) {
  const resultsContainer = $("resultsContainer");
  const statusBar = $("statusBar");
  const welcomeMessage = $("welcomeMessage");

  resultsContainer.innerHTML = '<div class="loading">Loading data...</div>';
  welcomeMessage.style.display = "none";

  try {
    const data = await adbClient.getTableData(tableName, currentLimit, offset);
    currentOffset = offset;
    totalCount = data.total_count;
    displayResults(data.columns, data.rows);
    updatePagination();
    statusBar.textContent = `${data.row_count} rows retrieved (${totalCount.toLocaleString()} total)`;
  } catch (err) {
    resultsContainer.innerHTML = `<div class="error">Failed to load data: ${err.message}</div>`;
  }
}

async function loadTableStructure(tableName) {
  const structureContainer = $("structureContainer");
  structureContainer.innerHTML = '<div class="loading">Loading structure...</div>';

  try {
    const columns = await adbClient.getTableStructure(tableName);
    const headers = ["cid", "name", "type", "notnull", "dflt_value", "pk"];

    structureContainer.innerHTML = `
      <table>
        <thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
        <tbody>
          ${columns.map((row) => `<tr>${headers.map((h) => `<td>${row[h] ?? ""}</td>`).join("")}</tr>`).join("")}
        </tbody>
      </table>`;
  } catch (err) {
    structureContainer.innerHTML = `<div class="error">Failed to load structure: ${err.message}</div>`;
  }
}

function getSelectedText() {
  const textarea = $("queryInput");
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  return start !== end ? textarea.value.substring(start, end).trim() : null;
}

async function executeQuery() {
  const selectedText = getSelectedText();
  const fullQuery = $("queryInput").value.trim();
  const query = selectedText || fullQuery;
  const isSelected = !!selectedText;

  const resultsContainer = $("resultsContainer");
  const statusBar = $("statusBar");
  const welcomeMessage = $("welcomeMessage");

  if (!query) {
    alert("Please enter a SQL query");
    return;
  }

  resultsContainer.innerHTML = '<div class="loading">Executing query...</div>';
  welcomeMessage.style.display = "none";
  statusBar.textContent = isSelected ? "Executing selected..." : "Executing...";

  try {
    const data = await adbClient.executeQuery(query, currentLimit);
    displayResults(data.columns, data.rows);
    statusBar.textContent = isSelected
      ? `${data.row_count} rows retrieved (selected query)`
      : `${data.row_count} rows retrieved`;
    $("pagination").style.display = "none";
  } catch (err) {
    resultsContainer.innerHTML = `<div class="error">Failed to execute query: ${err.message}</div>`;
    statusBar.textContent = "Error";
  }
}

async function executeAllQuery() {
  const fullQuery = $("queryInput").value.trim();
  const resultsContainer = $("resultsContainer");
  const statusBar = $("statusBar");
  const welcomeMessage = $("welcomeMessage");

  if (!fullQuery) {
    alert("Please enter a SQL query");
    return;
  }

  resultsContainer.innerHTML = '<div class="loading">Executing query...</div>';
  welcomeMessage.style.display = "none";
  statusBar.textContent = "Executing...";

  try {
    const data = await adbClient.executeQuery(fullQuery, currentLimit);
    displayResults(data.columns, data.rows);
    statusBar.textContent = `${data.row_count} rows retrieved`;
    $("pagination").style.display = "none";
  } catch (err) {
    resultsContainer.innerHTML = `<div class="error">Failed to execute query: ${err.message}</div>`;
    statusBar.textContent = "Error";
  }
}

// ──────────────── Display ────────────────

function displayResults(columns, rows) {
  const resultsContainer = $("resultsContainer");

  if (!rows || rows.length === 0) {
    resultsContainer.innerHTML = '<div class="info">No results found</div>';
    return;
  }

  const tableInfoHtml = `
    <div style="padding: 15px; background: #f8f9fa; border-bottom: 2px solid #dee2e6; font-size: 13px;">
      <strong>Table Information:</strong>
      <span style="margin-left: 20px;"><strong>Total Rows:</strong> ${totalCount ? totalCount.toLocaleString() : rows.length.toLocaleString()}</span>
      <span style="margin-left: 20px;"><strong>Total Columns:</strong> ${columns.length}</span>
      <span style="margin-left: 20px;"><strong>Columns:</strong> ${columns.join(", ")}</span>
    </div>`;

  resultsContainer.innerHTML =
    tableInfoHtml +
    `<table>
      <thead>
        <tr>
          <th style="background: #e9ecef; color: #495057; font-weight: 700;">#</th>
          ${columns.map((col) => `<th style="background: #e9ecef; color: #495057; font-weight: 700;">${col}</th>`).join("")}
        </tr>
      </thead>
      <tbody>
        ${rows
          .map(
            (row, index) => `
          <tr>
            <td style="background: #f8f9fa; font-weight: 600; color: #6c757d;">${currentOffset + index + 1}</td>
            ${columns.map((col) => `<td>${row[col] ?? '<span style="color: #999; font-style: italic;">NULL</span>'}</td>`).join("")}
          </tr>`
          )
          .join("")}
      </tbody>
    </table>`;
}

// ──────────────── Pagination ────────────────

function updatePagination() {
  const pagination = $("pagination");
  pagination.style.display = "flex";

  const currentPage = Math.floor(currentOffset / currentLimit) + 1;
  const totalPages = Math.ceil(totalCount / currentLimit);

  $("firstBtn").disabled = currentOffset === 0;
  $("prevBtn").disabled = currentOffset === 0;
  $("nextBtn").disabled = currentOffset + currentLimit >= totalCount;
  $("lastBtn").disabled = currentOffset + currentLimit >= totalCount;

  $("gotoPageInput").max = totalPages;
  $("gotoPageInput").placeholder = `1-${totalPages}`;
  $("pageInfo").textContent = `Page ${currentPage} of ${totalPages} (${totalCount.toLocaleString()} total rows)`;
}

function firstPage() {
  if (currentOffset > 0) loadTableData(currentTable, 0);
}

function previousPage() {
  if (currentOffset > 0) loadTableData(currentTable, currentOffset - currentLimit);
}

function nextPage() {
  if (currentOffset + currentLimit < totalCount)
    loadTableData(currentTable, currentOffset + currentLimit);
}

function lastPage() {
  if (currentOffset + currentLimit < totalCount) {
    const lastPageOffset = Math.floor((totalCount - 1) / currentLimit) * currentLimit;
    loadTableData(currentTable, lastPageOffset);
  }
}

function gotoPage() {
  const pageNumber = parseInt($("gotoPageInput").value);
  const totalPages = Math.ceil(totalCount / currentLimit);
  if (pageNumber >= 1 && pageNumber <= totalPages) {
    loadTableData(currentTable, (pageNumber - 1) * currentLimit);
    $("gotoPageInput").value = "";
  } else {
    alert(`Please enter a page number between 1 and ${totalPages}`);
  }
}

function changeLimit() {
  const newLimit = $("limitSelect").value;
  if (newLimit === "all") {
    currentLimit = totalCount || 100000;
  } else {
    currentLimit = parseInt(newLimit);
  }
  currentOffset = 0;
  if (currentTable) loadTableData(currentTable, 0);
}

// ──────────────── Tabs ────────────────

function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll(".tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.tab === tab);
  });
  document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));

  if (tab === "query") {
    $("queryTab").classList.add("active");
    if (currentTable) loadTableData(currentTable);
  } else if (tab === "structure") {
    $("structureTab").classList.add("active");
    if (currentTable) loadTableStructure(currentTable);
  }
}

// ──────────────── Toolbar actions ────────────────

async function refreshTables() {
  const statusBar = $("statusBar");
  statusBar.textContent = "Refreshing tables...";
  // Reset cached db path so it re-resolves
  adbClient.dbPath = "";
  await loadTables();
  await updateConnectionStatus();
  statusBar.textContent = "Tables refreshed";
  setTimeout(() => (statusBar.textContent = "Ready"), 3000);
}

function clearQuery() {
  $("queryInput").value = "";
  $("resultsContainer").innerHTML = "";
  $("welcomeMessage").style.display = "block";
  $("statusBar").textContent = "Ready";
  localStorage.removeItem("sqliteViewerQuery");
}

function formatQuery() {
  const textarea = $("queryInput");
  let query = textarea.value;
  query = query.replace(/\s+/g, " ").trim();
  query = query.replace(
    /\b(SELECT|FROM|WHERE|AND|OR|ORDER BY|GROUP BY|LIMIT|JOIN|LEFT JOIN|RIGHT JOIN|INNER JOIN)\b/gi,
    "\n$1"
  );
  query = query.replace(/,/g, ",\n  ");
  textarea.value = query;
}
