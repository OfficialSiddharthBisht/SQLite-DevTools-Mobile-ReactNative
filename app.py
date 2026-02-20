#!/usr/bin/env python3
"""
Flask Web Application for ADB SQLite Query Tool
Provides a web interface to query SQLite database on Android device via ADB
"""

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import sys
import os
import subprocess

# Load environment variables
load_dotenv()

# Add the python_tools directory to the path
PYTHON_TOOLS_PATH = os.getenv('PYTHON_TOOLS_PATH', '/Users/siddharth/Desktop/all-old/own-projects/winitsoftware/application1/python_tools')
sys.path.insert(0, PYTHON_TOOLS_PATH)

from adb_sqlite_query_tool import SQLiteADBQueryTool

app = Flask(__name__)
CORS(app)

# Global configuration - can be modified at runtime via API
app_config = {
    'package_name': os.getenv('PACKAGE_NAME', 'com.multiplex.winit'),
    'db_name': os.getenv('DB_NAME', 'WINITSQLite.db'),
    'db_path': os.getenv('DB_PATH', ''),  # Custom path, empty means auto-detect
    'device_serial': os.getenv('DEVICE_SERIAL', ''),
    'use_cache': os.getenv('USE_CACHE', 'True').lower() == 'true',
    'force_local': os.getenv('FORCE_LOCAL', 'False').lower() == 'true'
}

def get_adb_tool():
    """Get or create ADB tool instance with current configuration"""
    return SQLiteADBQueryTool(
        package_name=app_config['package_name'],
        db_name=app_config['db_name'],
        force_local=app_config['force_local'],
        use_cache=app_config['use_cache'],
        device_serial=app_config['device_serial'] if app_config['device_serial'] else None
    )

@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')

@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Get list of connected ADB devices"""
    try:
        result = subprocess.run(['adb', 'devices', '-l'],
                              capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            return jsonify({'success': False, 'error': 'ADB command failed'})

        devices = []
        lines = result.stdout.strip().split('\n')[1:]  # Skip header

        for line in lines:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == 'device':
                serial = parts[0]
                # Parse device info from the -l output
                model = ''
                product = ''
                for part in parts[2:]:
                    if part.startswith('model:'):
                        model = part.split(':')[1]
                    elif part.startswith('product:'):
                        product = part.split(':')[1]

                devices.append({
                    'serial': serial,
                    'model': model,
                    'product': product,
                    'display_name': f"{model or product or serial} ({serial})"
                })

        return jsonify({
            'success': True,
            'devices': devices,
            'current_device': app_config['device_serial']
        })

    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'ADB command timed out'})
    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'ADB not found. Make sure Android SDK is installed.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/packages', methods=['GET'])
def get_packages():
    """Get list of debuggable packages on the selected device"""
    try:
        device_serial = request.args.get('device', app_config['device_serial'])

        # Build ADB base command with optional device serial
        adb_base = ['adb']
        if device_serial:
            adb_base.extend(['-s', device_serial])

        # Single shell command: list third-party packages, then test each with run-as
        # run-as only works on debuggable apps, so this filters automatically
        # --user 0: target main user only (avoids SecurityException on multi-user/work profile devices)
        # tr -d '\\r': strips carriage returns from Android's CRLF line endings
        shell_script = (
            'for p in $(pm list packages --user 0 -3 2>/dev/null | tr -d "\\r" | sed "s/package://"); do '
            'run-as $p id 2>/dev/null 1>/dev/null && echo $p; '
            'done'
        )
        cmd = adb_base + ['shell', shell_script]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        # Don't check returncode — the for loop returns the exit code of the last
        # run-as which is non-zero if the last package isn't debuggable

        packages = []
        for line in result.stdout.strip().split('\n'):
            package_name = line.strip()
            if package_name:
                packages.append(package_name)

        # Sort packages alphabetically
        packages.sort()

        return jsonify({
            'success': True,
            'packages': packages,
            'current_package': app_config['package_name']
        })

    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Scanning debuggable packages timed out (this can take a while on first load)'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current configuration"""
    return jsonify({
        'success': True,
        'config': {
            'device_serial': app_config['device_serial'],
            'package_name': app_config['package_name'],
            'db_name': app_config['db_name'],
            'db_path': app_config['db_path'],
            'use_cache': app_config['use_cache'],
            'force_local': app_config['force_local']
        }
    })

@app.route('/api/config', methods=['POST'])
def update_config():
    """Update configuration settings"""
    try:
        data = request.json

        # Update configuration with provided values
        if 'device_serial' in data:
            app_config['device_serial'] = data['device_serial']
        if 'package_name' in data:
            app_config['package_name'] = data['package_name']
        if 'db_name' in data:
            app_config['db_name'] = data['db_name']
        if 'db_path' in data:
            app_config['db_path'] = data['db_path']
        if 'use_cache' in data:
            app_config['use_cache'] = bool(data['use_cache'])
        if 'force_local' in data:
            app_config['force_local'] = bool(data['force_local'])

        return jsonify({
            'success': True,
            'message': 'Configuration updated successfully',
            'config': app_config
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/databases', methods=['GET'])
def get_databases():
    """Get list of SQLite databases for the selected package"""
    try:
        device_serial = request.args.get('device', app_config['device_serial'])
        package_name = request.args.get('package', app_config['package_name'])

        # Build ADB command
        adb_cmd = ['adb']
        if device_serial:
            adb_cmd.extend(['-s', device_serial])

        databases = []

        # Check multiple possible database locations
        db_locations = ['databases', 'files', 'files/SQLite']

        for location in db_locations:
            cmd = adb_cmd + ['shell', f'run-as {package_name} ls {location} 2>/dev/null']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                for file in result.stdout.strip().split('\n'):
                    file = file.strip()
                    if file and (file.endswith('.db') or file.endswith('.sqlite') or file.endswith('.sqlite3')):
                        databases.append({
                            'name': file,
                            'path': f'{location}/{file}'
                        })

        # Remove duplicates based on name
        seen = set()
        unique_databases = []
        for db in databases:
            if db['name'] not in seen:
                seen.add(db['name'])
                unique_databases.append(db)

        return jsonify({
            'success': True,
            'databases': unique_databases,
            'current_db': app_config['db_name']
        })

    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'ADB command timed out'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/search-databases', methods=['GET'])
def search_databases():
    """Search for SQLite database files within a package's data directory"""
    try:
        device_serial = request.args.get('device', app_config['device_serial'])
        package_name = request.args.get('package', app_config['package_name'])
        search_query = request.args.get('q', '').strip().lower()

        # Build ADB command
        adb_cmd = ['adb']
        if device_serial:
            adb_cmd.extend(['-s', device_serial])

        # Use find to recursively search for db files
        cmd = adb_cmd + ['shell', f'run-as {package_name} find . -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" 2>/dev/null']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        databases = []
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                file_path = line.strip()
                if not file_path:
                    continue
                # Clean up the path (remove leading ./)
                if file_path.startswith('./'):
                    file_path = file_path[2:]
                file_name = file_path.split('/')[-1]
                # Skip journal/wal/shm files
                if file_name.endswith('-journal') or file_name.endswith('-wal') or file_name.endswith('-shm'):
                    continue
                databases.append({
                    'name': file_name,
                    'path': file_path
                })

        # Apply search filter if provided
        if search_query:
            databases = [db for db in databases if search_query in db['name'].lower() or search_query in db['path'].lower()]

        # Sort by name
        databases.sort(key=lambda x: x['name'].lower())

        return jsonify({
            'success': True,
            'databases': databases,
            'current_db': app_config['db_name']
        })

    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Search timed out'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/check-connection', methods=['GET'])
def check_connection():
    """Check if ADB device is connected"""
    try:
        tool = get_adb_tool()
        if not tool.check_adb_connection():
            return jsonify({'success': False, 'error': 'No ADB device connected'})

        if not tool.check_database_exists():
            return jsonify({'success': False, 'error': 'Database not found on device'})

        return jsonify({'success': True, 'message': 'Connected to device'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/tables', methods=['GET'])
def get_tables():
    """Get list of all tables with row counts"""
    try:
        tool = get_adb_tool()

        # Check connection first
        if not tool.check_adb_connection():
            return jsonify({'success': False, 'error': 'No ADB device connected'})

        if not tool.check_database_exists():
            return jsonify({'success': False, 'error': 'Database not found on device'})

        # Get tables
        tables = tool.get_table_list()

        # Get row counts for each table
        table_info = []
        for table in tables:
            # count = tool.get_table_count(table)
            table_info.append({
                'name': table,
                'row_count': 0
            })

        return jsonify({'success': True, 'tables': table_info})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/table-structure/<table_name>', methods=['GET'])
def get_table_structure(table_name):
    """Get structure/schema of a specific table"""
    try:
        tool = get_adb_tool()

        # Check connection first
        if not tool.check_adb_connection():
            return jsonify({'success': False, 'error': 'No ADB device connected'})

        columns = tool.get_table_info(table_name)

        if not columns:
            return jsonify({'success': False, 'error': f'Table {table_name} not found'})

        return jsonify({'success': True, 'columns': columns})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/query', methods=['POST'])
def execute_query():
    """Execute a SQL query"""
    try:
        data = request.json
        query = data.get('query', '').strip()
        limit = data.get('limit', 100)

        if not query:
            return jsonify({'success': False, 'error': 'No query provided'})

        tool = get_adb_tool()

        # Check connection first
        if not tool.check_adb_connection():
            return jsonify({'success': False, 'error': 'No ADB device connected'})

        # Execute query
        results = tool.execute_query(query, limit=limit)

        if results is None:
            error_msg = tool.last_error if tool.last_error else 'Query execution failed'
            return jsonify({'success': False, 'error': error_msg})

        # Get column names from first result if available
        columns = list(results[0].keys()) if results else []

        return jsonify({
            'success': True,
            'columns': columns,
            'rows': results,
            'row_count': len(results)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/table-data/<table_name>', methods=['GET'])
def get_table_data(table_name):
    """Get data from a specific table"""
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)

        # Support very large limits (for "All" option)
        if limit > 100000:
            limit = 100000  # Cap at 100k rows for safety

        tool = get_adb_tool()

        # Check connection first
        if not tool.check_adb_connection():
            return jsonify({'success': False, 'error': 'No ADB device connected'})

        # Get table structure
        columns_info = tool.get_table_info(table_name)
        if not columns_info:
            return jsonify({'success': False, 'error': f'Table {table_name} not found'})

        # Get data
        query = f"SELECT * FROM {table_name} LIMIT {limit} OFFSET {offset}"
        results = tool.execute_query(query)

        if results is None:
            return jsonify({'success': False, 'error': 'Failed to fetch data'})

        # Get total count
        total_count = tool.get_table_count(table_name)

        return jsonify({
            'success': True,
            'columns': [col['name'] for col in columns_info],
            'rows': results,
            'row_count': len(results),
            'total_count': total_count,
            'offset': offset,
            'limit': limit
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/clear-cache', methods=['POST'])
def clear_cache():
    """Clear database cache only"""
    try:
        tool = get_adb_tool()

        if tool.clear_cache():
            return jsonify({
                'success': True,
                'message': 'Cache cleared successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to clear cache'
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/force-pull', methods=['POST'])
def force_pull():
    """Force pull fresh database from device (clears cache first)"""
    try:
        import tempfile
        from pathlib import Path

        tool = get_adb_tool()

        # Check connection first
        if not tool.check_adb_connection():
            return jsonify({'success': False, 'error': 'No ADB device connected'})

        if not tool.check_database_exists():
            return jsonify({'success': False, 'error': 'Database not found on device'})

        # Clear cache first
        tool.clear_cache()

        # Force pull with cache enabled (so it saves to cache directory)
        # but force_pull=True bypasses the cache check and re-pulls
        tool_force = SQLiteADBQueryTool(
            package_name=app_config['package_name'],
            db_name=app_config['db_name'],
            force_local=True,
            use_cache=True,
            force_pull=True,
            device_serial=app_config['device_serial'] if app_config['device_serial'] else None
        )

        # Pull fresh database
        if not tool_force.pull_database():
            return jsonify({'success': False, 'error': 'Failed to pull database from device'})

        # Fix gzip decompression issue
        cache_dir = Path(tempfile.gettempdir()) / "adb_sqlite_cache"
        db_file = cache_dir / f"{app_config['package_name']}_{app_config['db_name']}"

        if db_file.exists():
            # Check if file is gzipped (Windows compatible check)
            try:
                with open(db_file, 'rb') as f:
                    magic = f.read(2)
                if magic == b'\x1f\x8b':  # gzip magic number
                    print(f"Detected gzipped database, decompressing...")
                    import gzip
                    import shutil
                    gz_file = str(db_file) + '.gz'
                    db_file.rename(gz_file)
                    with gzip.open(gz_file, 'rb') as f_in:
                        with open(db_file, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    os.unlink(gz_file)
                    print(f"Database decompressed successfully")
            except Exception as e:
                print(f"Warning: Could not check/decompress file: {e}")

        return jsonify({
            'success': True,
            'message': 'Fresh database pulled from device (cache bypassed)'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/refresh-database', methods=['POST'])
def refresh_database():
    """Force refresh database from device"""
    try:
        import tempfile
        from pathlib import Path

        tool = get_adb_tool()

        # Check connection first
        if not tool.check_adb_connection():
            return jsonify({'success': False, 'error': 'No ADB device connected'})

        if not tool.check_database_exists():
            return jsonify({'success': False, 'error': 'Database not found on device'})

        # Clear cache and force pull
        tool.clear_cache()

        # Pull fresh database
        if not tool.pull_database():
            return jsonify({'success': False, 'error': 'Failed to pull database from device'})

        # Fix gzip decompression issue
        cache_dir = Path(tempfile.gettempdir()) / "adb_sqlite_cache"
        db_file = cache_dir / f"{app_config['package_name']}_{app_config['db_name']}"

        if db_file.exists():
            # Check if file is gzipped (Windows compatible check)
            try:
                with open(db_file, 'rb') as f:
                    magic = f.read(2)
                if magic == b'\x1f\x8b':  # gzip magic number
                    print(f"Detected gzipped database, decompressing...")
                    import gzip
                    import shutil
                    gz_file = str(db_file) + '.gz'
                    db_file.rename(gz_file)
                    with gzip.open(gz_file, 'rb') as f_in:
                        with open(db_file, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    os.unlink(gz_file)
                    print(f"Database decompressed successfully")
            except Exception as e:
                print(f"Warning: Could not check/decompress file: {e}")

        return jsonify({
            'success': True,
            'message': 'Database refreshed successfully from device'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    # Load Flask configuration from environment
    FLASK_HOST = os.getenv('FLASK_HOST', '0.0.0.0')
    FLASK_PORT = int(os.getenv('FLASK_PORT', '5001'))
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'

    print("Starting ADB SQLite Query Viewer...")
    print(f"Open http://localhost:{FLASK_PORT} in your browser")
    app.run(debug=FLASK_DEBUG, host=FLASK_HOST, port=FLASK_PORT)
