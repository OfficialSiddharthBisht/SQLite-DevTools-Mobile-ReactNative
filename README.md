# SQLite DevTools for Mobile (React Native)

A browser-based tool for inspecting SQLite databases on Android devices. Browse tables, view schemas, and execute SQL queries directly on your device.

## Four Ways to Use

### Option 1: Desktop App (Easiest)

Download the installer from [Releases](https://github.com/amitwinit/SQLite-DevTools-Mobile-ReactNative/releases) and run it. The app bundles the ADB bridge server — it starts automatically when you launch the app. No separate downloads, no terminal commands.

**Requirements:**
- Windows (NSIS installer)
- `adb` on your PATH (Android SDK Platform-Tools)
- Android device with USB debugging enabled

### Option 2: Hosted Version + ADB Bridge (Best for React Native Developers)

Use the deployed version at **[amitwinit.github.io/SQLite-DevTools-Mobile-ReactNative](https://amitwinit.github.io/SQLite-DevTools-Mobile-ReactNative/)** together with the **ADB Bridge** — a small localhost server that wraps `adb shell` commands. This lets you inspect databases while ADB stays running for React Native development.

**Setup:**

1. Download `adb-bridge.exe` from [Releases](https://github.com/amitwinit/SQLite-DevTools-Mobile-ReactNative/releases), or build it yourself:
   ```bash
   cd bridge
   npm install
   npm run build    # produces adb-bridge.exe
   ```

2. Run the bridge:
   ```bash
   # Either run the exe directly:
   adb-bridge.exe

   # Or with Node.js:
   cd bridge && node server.js
   ```

3. Open the hosted website — it auto-detects the bridge and connects through it.

**How it works:**
```
Hosted website (HTTPS) ──HTTP──> localhost:15555 (bridge) ──> adb shell ──> Device
```
The website detects the bridge on startup and routes all commands through HTTP instead of WebUSB. No need to kill ADB.

### Option 3: Hosted Version with WebUSB (No Setup Required)

Use the deployed version at **[amitwinit.github.io/SQLite-DevTools-Mobile-ReactNative](https://amitwinit.github.io/SQLite-DevTools-Mobile-ReactNative/)**

This version uses **WebUSB** to communicate with your Android device directly from the browser. No backend server needed.

**Requirements:**
- Chrome or Edge (WebUSB is not supported in Firefox/Safari)
- Android device with USB debugging enabled
- You must **stop the local ADB server** first: `adb kill-server`

**Important:** WebUSB and the local ADB server cannot use the USB interface at the same time. If you are actively developing a React Native app and need ADB running, use **Option 1** or **Option 2** instead.

**Steps:**
1. Run `adb kill-server` in your terminal
2. Open the hosted URL in Chrome/Edge
3. Click **Connect Device** and select your phone from the USB picker
4. Approve the USB debugging prompt on your phone (first time only)
5. Select a package and database, then start querying

### Option 4: Local Flask Server (Legacy)

If you are developing a React Native app and need ADB running alongside, use the local Flask backend. Both tools share the same ADB server so there is no conflict.

**Setup:**

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Copy and configure environment:
   ```bash
   cp .env.example .env
   ```

   Update `.env` with your configuration:
   - `DEVICE_SERIAL` — run `adb devices` to find it
   - `PACKAGE_NAME` — your app's package name
   - `DB_NAME` — the SQLite database filename
   - `PYTHON_TOOLS_PATH` — path to the python_tools directory

3. Run the server:
   ```bash
   python app.py
   ```

4. Open http://localhost:5001 in any browser

## When to Use Which

| Scenario | Use |
|----------|-----|
| Just want it to work, one click | Desktop App (Option 1) |
| Active React Native development | Desktop App (Option 1) or ADB Bridge (Option 2) |
| Quick DB inspection, no local setup | WebUSB (Option 3) |
| Sharing with teammates who don't have Python | WebUSB (Option 3) |
| Need ADB for other tools simultaneously | Desktop App (Option 1) or ADB Bridge (Option 2) |

## Environment Variables (Option 4)

### Application Configuration
- `PACKAGE_NAME`: Android app package name
- `DB_NAME`: Database name on the device
- `DEVICE_SERIAL`: ADB device serial number
- `PYTHON_TOOLS_PATH`: Path to python_tools directory

### Flask Server Configuration
- `FLASK_HOST`: Flask server host (default: 0.0.0.0)
- `FLASK_PORT`: Flask server port (default: 5001)
- `FLASK_DEBUG`: Enable debug mode (default: True)

### Cache Configuration
- `USE_CACHE`: Enable database caching (default: True)
- `FORCE_LOCAL`: Force local database operations (default: False)

## Development

To work on the WebUSB frontend:

```bash
npm install
npm run dev
```

To build for production (GitHub Pages):

```bash
npm run build
```

The built files go to `dist/` and are deployed to GitHub Pages automatically on push to `main`.

To run the Electron desktop app in development:

```bash
npm run electron:dev
```

To build the Electron installer:

```bash
npm run electron:build
```

The installer is output to `electron-dist/`.
