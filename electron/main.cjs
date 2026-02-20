const { app, BrowserWindow } = require("electron");
const { fork } = require("child_process");
const path = require("path");

let bridge = null;
let mainWindow = null;

function getBridgePath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "bridge", "server.js");
  }
  return path.join(__dirname, "..", "bridge", "server.js");
}

function startBridge() {
  return new Promise((resolve, reject) => {
    const serverPath = getBridgePath();
    bridge = fork(serverPath, [], { silent: true });

    const timeout = setTimeout(() => {
      reject(new Error("Bridge server failed to start within 10 seconds"));
    }, 10_000);

    bridge.on("message", (msg) => {
      if (msg.type === "ready") {
        clearTimeout(timeout);
        resolve();
      } else if (msg.type === "error") {
        clearTimeout(timeout);
        reject(new Error(msg.message || "Bridge error"));
      }
    });

    bridge.on("error", (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    bridge.on("exit", (code) => {
      if (code !== 0 && code !== null) {
        clearTimeout(timeout);
        reject(new Error(`Bridge exited with code ${code}`));
      }
    });

    // Forward bridge logs to main process console
    bridge.stdout.on("data", (data) => {
      process.stdout.write(`[bridge] ${data}`);
    });
    bridge.stderr.on("data", (data) => {
      process.stderr.write(`[bridge] ${data}`);
    });
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  // __dirname works in both dev and packaged (asar transparency)
  const indexPath = path.join(__dirname, "..", "dist", "index.html");

  mainWindow.loadFile(indexPath);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(async () => {
  try {
    console.log("Starting ADB bridge server...");
    await startBridge();
    console.log("Bridge server ready.");
  } catch (err) {
    console.error("Failed to start bridge:", err.message);
    // Continue anyway — user can still use the app if they have standalone bridge
  }

  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  if (bridge) {
    bridge.kill();
    bridge = null;
  }
});
