# SQLite DevTools for Mobile (React Native)

A browser-based tool for inspecting SQLite databases on Android devices. Browse tables, view schemas, and execute SQL queries directly on your device.

## Two Ways to Use

### Option 1: Hosted Version (No Setup Required)

Use the deployed version at **[amitwinit.github.io/SQLite-DevTools-Mobile-ReactNative](https://amitwinit.github.io/SQLite-DevTools-Mobile-ReactNative/)**

This version uses **WebUSB** to communicate with your Android device directly from the browser. No backend server needed.

**Requirements:**
- Chrome or Edge (WebUSB is not supported in Firefox/Safari)
- Android device with USB debugging enabled
- You must **stop the local ADB server** first: `adb kill-server`

**Important:** WebUSB and the local ADB server cannot use the USB interface at the same time. If you are actively developing a React Native app and need ADB running, use **Option 2** instead.

**Steps:**
1. Run `adb kill-server` in your terminal
2. Open the hosted URL in Chrome/Edge
3. Click **Connect Device** and select your phone from the USB picker
4. Approve the USB debugging prompt on your phone (first time only)
5. Select a package and database, then start querying

### Option 2: Local Flask Server (For React Native Developers)

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
| Quick DB inspection, no local setup | Hosted version (Option 1) |
| Active React Native development | Local Flask server (Option 2) |
| Sharing with teammates who don't have Python | Hosted version (Option 1) |
| Need ADB for other tools simultaneously | Local Flask server (Option 2) |

## Environment Variables (Option 2)

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

To build for production:

```bash
npm run build
```

The built files go to `dist/` and are deployed to GitHub Pages automatically on push to `main`.
