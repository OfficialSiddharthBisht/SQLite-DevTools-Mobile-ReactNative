/**
 * Browser-based ADB Client using WebUSB + Tango ADB.
 * Replaces all Flask backend API calls with direct device communication.
 */
import { Adb, AdbDaemonTransport } from "@yume-chan/adb";
import { AdbDaemonWebUsbDeviceManager } from "@yume-chan/adb-daemon-webusb";
import AdbWebCredentialStore from "@yume-chan/adb-credential-web";

const Manager = AdbDaemonWebUsbDeviceManager.BROWSER;
const credentialStore = new AdbWebCredentialStore();

export class AdbClient {
  constructor() {
    /** @type {Adb|null} */
    this.adb = null;
    /** @type {import("@yume-chan/adb-daemon-webusb").AdbDaemonWebUsbDevice|null} */
    this.device = null;
    /** @type {string} */
    this.packageName = "";
    /** @type {string} */
    this.dbName = "";
    /** @type {string} */
    this.dbPath = "";
    /** @type {string} */
    this.sqlite3Path = "";
  }

  // ──────────────── Connection ────────────────

  /**
   * Show the browser USB device picker and connect.
   * Must be called from a user gesture (click).
   */
  async requestDevice() {
    if (!Manager) {
      throw new Error(
        "WebUSB is not supported in this browser. Use Chrome or Edge."
      );
    }
    const device = await Manager.requestDevice();
    if (!device) throw new Error("No device selected.");
    await this._connectDevice(device);
    return this.getDeviceInfo();
  }

  /**
   * List already-paired WebUSB devices (no picker needed).
   */
  async getDevices() {
    if (!Manager) return [];
    const devices = await Manager.getDevices();
    return devices.map((d) => ({
      serial: d.serial,
      name: d.name,
      display_name: `${d.name || d.serial} (${d.serial})`,
    }));
  }

  /**
   * Connect to a specific previously-paired device by serial.
   */
  async connectBySerial(serial) {
    if (!Manager) throw new Error("WebUSB not supported.");
    const devices = await Manager.getDevices();
    const target = devices.find((d) => d.serial === serial);
    if (!target) throw new Error(`Device ${serial} not found.`);
    await this._connectDevice(target);
    return this.getDeviceInfo();
  }

  /** Internal: establish ADB transport to a device */
  async _connectDevice(device) {
    // Disconnect existing connection first
    await this.disconnect();

    let connection;
    try {
      connection = await device.connect();
    } catch (err) {
      if (err?.message?.includes("claimInterface")) {
        throw new Error(
          "Cannot claim USB device — another program (likely ADB) is using it. " +
          "Run 'adb kill-server' in your terminal, then retry."
        );
      }
      throw err;
    }
    const transport = await AdbDaemonTransport.authenticate({
      serial: device.serial,
      connection,
      credentialStore,
    });
    this.adb = new Adb(transport);
    this.device = device;
  }

  async disconnect() {
    if (this.adb) {
      try {
        await this.adb.close();
      } catch {
        /* ignore */
      }
      this.adb = null;
      this.device = null;
    }
  }

  checkConnection() {
    return {
      connected: !!this.adb,
      device: this.adb ? this.getDeviceInfo() : null,
      package: this.packageName,
      database: this.dbName,
    };
  }

  getDeviceInfo() {
    if (!this.device) return null;
    return {
      serial: this.device.serial,
      name: this.device.name,
      display_name: `${this.device.name || this.device.serial} (${this.device.serial})`,
    };
  }

  // ──────────────── Configuration ────────────────

  setPackage(packageName) {
    this.packageName = packageName;
    this.dbName = "";
    this.dbPath = "";
    this.sqlite3Path = "";
  }

  setDatabase(dbName, dbPath) {
    this.dbName = dbName;
    this.dbPath = dbPath || "";
  }

  // ──────────────── Shell helpers ────────────────

  /**
   * Run a shell command and return stdout text.
   * Strips trailing \r\n from Android output.
   */
  async shell(command) {
    if (!this.adb) throw new Error("Not connected to a device.");
    const output = await this.adb.subprocess.spawnAndWaitLegacy(command);
    // spawnAndWaitLegacy may return string, Uint8Array, or {stdout, stderr}.
    let text;
    if (typeof output === "string") {
      text = output;
    } else if (output instanceof Uint8Array) {
      text = new TextDecoder().decode(output);
    } else if (output?.stdout !== undefined) {
      text = typeof output.stdout === "string"
        ? output.stdout
        : new TextDecoder().decode(output.stdout);
    } else {
      text = String(output);
    }
    return text.replace(/\r\n/g, "\n").trimEnd();
  }

  /** Run a shell command under `run-as <package>` */
  async runAs(command) {
    return this.shell(`run-as ${this.packageName} ${command}`);
  }

  // ──────────────── Packages ────────────────

  /**
   * Get debuggable packages on the device.
   * Mirrors the logic from the Python backend.
   */
  async getPackages() {
    const script =
      'for p in $(pm list packages --user 0 -3 2>/dev/null | tr -d "\\r" | sed "s/package://"); do ' +
      "run-as $p id 2>/dev/null 1>/dev/null && echo $p; " +
      "done";
    const output = await this.shell(script);
    const packages = output
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    packages.sort();
    return packages;
  }

  // ──────────────── Databases ────────────────

  async getDatabases(packageName) {
    const pkg = packageName || this.packageName;
    if (!pkg) throw new Error("No package selected.");

    const locations = ["databases", "files", "files/SQLite"];
    const databases = [];
    const seen = new Set();

    for (const loc of locations) {
      try {
        const out = await this.shell(
          `run-as ${pkg} ls ${loc} 2>/dev/null`
        );
        for (const file of out.split("\n")) {
          const f = file.trim();
          if (
            f &&
            (f.endsWith(".db") ||
              f.endsWith(".sqlite") ||
              f.endsWith(".sqlite3"))
          ) {
            if (!seen.has(f)) {
              seen.add(f);
              databases.push({ name: f, path: `${loc}/${f}` });
            }
          }
        }
      } catch {
        /* location may not exist */
      }
    }
    return databases;
  }

  async searchDatabases(packageName, query) {
    const pkg = packageName || this.packageName;
    if (!pkg) throw new Error("No package selected.");

    const out = await this.shell(
      `run-as ${pkg} find . -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" 2>/dev/null`
    );

    const q = (query || "").toLowerCase();
    const databases = [];

    for (const line of out.split("\n")) {
      let filePath = line.trim();
      if (!filePath) continue;
      if (filePath.startsWith("./")) filePath = filePath.slice(2);
      const fileName = filePath.split("/").pop();
      if (
        fileName.endsWith("-journal") ||
        fileName.endsWith("-wal") ||
        fileName.endsWith("-shm")
      )
        continue;

      if (!q || fileName.toLowerCase().includes(q) || filePath.toLowerCase().includes(q)) {
        databases.push({ name: fileName, path: filePath });
      }
    }
    databases.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    return databases;
  }

  // ──────────────── sqlite3 setup ────────────────

  /**
   * Ensure sqlite3 is available inside the app sandbox.
   * Mirrors ensure_sqlite3_on_device() from Python backend.
   */
  async ensureSqlite3() {
    if (this.sqlite3Path) return this.sqlite3Path;

    // 1. Check app dir
    try {
      const v = await this.runAs("./sqlite3 -version");
      if (v.includes("3.") || v.toLowerCase().includes("sqlite")) {
        this.sqlite3Path = "./sqlite3";
        return this.sqlite3Path;
      }
    } catch {
      /* not there */
    }

    // 2. Check system paths
    const systemPaths = [
      "/system/bin/sqlite3",
      "/system/xbin/sqlite3",
      "/data/local/tmp/sqlite3",
    ];
    for (const p of systemPaths) {
      try {
        const v = await this.shell(`${p} -version 2>&1`);
        if (v.includes("3.") || v.toLowerCase().includes("sqlite")) {
          // Try to copy into app dir
          try {
            await this.runAs(`cp ${p} ./sqlite3`);
            await this.runAs("chmod 755 ./sqlite3");
            const verify = await this.runAs("./sqlite3 -version");
            if (verify.includes("3.")) {
              this.sqlite3Path = "./sqlite3";
              return this.sqlite3Path;
            }
          } catch {
            /* copy failed, use system path */
          }
          this.sqlite3Path = p;
          return this.sqlite3Path;
        }
      } catch {
        /* not at this path */
      }
    }

    throw new Error(
      "sqlite3 not found on device. Ensure a sqlite3 binary is available at /system/bin/sqlite3 or /data/local/tmp/sqlite3."
    );
  }

  // ──────────────── Database path resolution ────────────────

  async findDatabasePath() {
    if (this.dbPath) return this.dbPath;

    const candidates = [
      `databases/${this.dbName}`,
      `files/${this.dbName}`,
      `files/SQLite/${this.dbName}`,
    ];

    for (const p of candidates) {
      try {
        const out = await this.runAs(`ls ${p}`);
        if (out.includes(this.dbName)) {
          this.dbPath = p;
          return p;
        }
      } catch {
        /* not found */
      }
    }
    throw new Error(`Database ${this.dbName} not found on device.`);
  }

  // ──────────────── Query execution ────────────────

  /**
   * Run a sqlite3 command and return parsed JSON rows.
   * Uses `-json` output mode.
   */
  async _sqliteJson(sql) {
    const sqlite = await this.ensureSqlite3();
    const dbPath = await this.findDatabasePath();

    // Escape for shell
    const escaped = sql
      .replace(/\\/g, "\\\\")
      .replace(/"/g, '\\"')
      .replace(/\$/g, "\\$")
      .replace(/`/g, "\\`");

    const cmd = `${sqlite} ${dbPath} -json "${escaped}"`;
    const out = await this.runAs(cmd);

    if (!out) return [];
    try {
      const parsed = JSON.parse(out);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      // Fallback: try header+pipe mode
      return this._sqliteFallback(sql, sqlite, dbPath);
    }
  }

  /** Fallback parser when -json is not supported */
  async _sqliteFallback(sql, sqlite, dbPath) {
    const escaped = sql
      .replace(/\\/g, "\\\\")
      .replace(/"/g, '\\"')
      .replace(/\$/g, "\\$")
      .replace(/`/g, "\\`");

    const cmd = `${sqlite} ${dbPath} -header -separator "|" "${escaped}"`;
    const out = await this.runAs(cmd);
    const lines = out.split("\n").filter(Boolean);
    if (lines.length === 0) return [];

    const headers = lines[0].split("|").map((h) => h.trim());
    const rows = [];
    for (let i = 1; i < lines.length; i++) {
      const vals = lines[i].split("|").map((v) => v.trim());
      if (vals.length === headers.length) {
        const row = {};
        headers.forEach((h, idx) => (row[h] = vals[idx]));
        rows.push(row);
      }
    }
    return rows;
  }

  /** Execute a write command (INSERT/UPDATE/DELETE). Returns void. */
  async _sqliteExec(sql) {
    const sqlite = await this.ensureSqlite3();
    const dbPath = await this.findDatabasePath();

    const escaped = sql
      .replace(/\\/g, "\\\\")
      .replace(/"/g, '\\"')
      .replace(/\$/g, "\\$")
      .replace(/`/g, "\\`");

    const cmd = `${sqlite} ${dbPath} "${escaped}"`;
    await this.runAs(cmd);
  }

  _isWriteQuery(sql) {
    const upper = sql.trim().toUpperCase();
    return ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "REPLACE"].some(
      (op) => upper.startsWith(op)
    );
  }

  // ──────────────── Public API (matches old Flask endpoints) ────────────────

  async getTables() {
    const rows = await this._sqliteJson(
      "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
    );
    return rows.map((r) => ({ name: r.name, row_count: 0 }));
  }

  async getTableStructure(tableName) {
    return this._sqliteJson(`PRAGMA table_info(${tableName});`);
  }

  async getTableData(tableName, limit = 100, offset = 0) {
    const columns = await this.getTableStructure(tableName);
    if (!columns.length) throw new Error(`Table ${tableName} not found`);

    const rows = await this._sqliteJson(
      `SELECT * FROM ${tableName} LIMIT ${limit} OFFSET ${offset};`
    );
    const countResult = await this._sqliteJson(
      `SELECT COUNT(*) as count FROM ${tableName};`
    );
    const totalCount = countResult.length ? Number(countResult[0].count) : 0;

    return {
      columns: columns.map((c) => c.name),
      rows,
      row_count: rows.length,
      total_count: totalCount,
      offset,
      limit,
    };
  }

  async executeQuery(sql, limit) {
    const trimmed = sql.trim();
    if (this._isWriteQuery(trimmed)) {
      await this._sqliteExec(trimmed);
      return { columns: [], rows: [], row_count: 0 };
    }

    // Append LIMIT if not already present (for SELECT only)
    let finalSql = trimmed;
    if (
      limit &&
      !trimmed.toUpperCase().includes("LIMIT") &&
      trimmed.toUpperCase().startsWith("SELECT")
    ) {
      finalSql = `${trimmed.replace(/;$/, "")} LIMIT ${limit};`;
    }

    const rows = await this._sqliteJson(finalSql);
    const columns = rows.length ? Object.keys(rows[0]) : [];
    return { columns, rows, row_count: rows.length };
  }

  async checkDatabaseExists() {
    try {
      await this.findDatabasePath();
      return true;
    } catch {
      return false;
    }
  }
}
