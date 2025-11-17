# ADB Query Viewer

A Flask web application for querying SQLite databases on Android devices via ADB.

## Setup

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Update `.env` with your specific configuration:
   - Set `DEVICE_SERIAL` (use `adb devices` to find it)
   - Update `PYTHON_TOOLS_PATH` to match your project structure
   - Adjust other settings as needed

3. Install dependencies:
   ```bash
   pip3 install -r requirements.txt
   ```

4. Run the application:
   ```bash
   python3 app.py
   ```

5. Open http://localhost:5001 in your browser

## Environment Variables

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

### Test Script Configuration
- `TABLE_LIST`: Comma-separated list of tables for show_table_info.sh
- `TEST_TABLE`: Primary table for test scripts (default: tblProducts)
- `TEST_TABLE_2`: Secondary table for test scripts (default: tblCustomer)

## Utility Scripts

All shell scripts now read configuration from the `.env` file:

- `show_table_info.sh` - Display information about tables defined in TABLE_LIST
- `test_features.sh` - Test pagination and basic API features
- `test_cache_features.sh` - Test cache control features
- `fix_db_cache.sh` - Fix gzip decompression issues in cached database
# SQLite-DevTools-Mobile-ReactNative
