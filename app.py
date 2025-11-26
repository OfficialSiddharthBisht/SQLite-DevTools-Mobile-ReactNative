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

# Load environment variables
load_dotenv()

# Add the python_tools directory to the path
PYTHON_TOOLS_PATH = os.getenv('PYTHON_TOOLS_PATH', '/Users/siddharth/Desktop/all-old/own-projects/winitsoftware/application1/python_tools')
sys.path.insert(0, PYTHON_TOOLS_PATH)

from adb_sqlite_query_tool import SQLiteADBQueryTool

app = Flask(__name__)
CORS(app)

# Load configuration from environment variables
PACKAGE_NAME = os.getenv('PACKAGE_NAME', 'com.multiplex.winit')
DB_NAME = os.getenv('DB_NAME', 'WINITSQLite.db')
DEVICE_SERIAL = os.getenv('DEVICE_SERIAL', 'R8AYE6DINBTOGUK7')
USE_CACHE = os.getenv('USE_CACHE', 'True').lower() == 'true'
FORCE_LOCAL = os.getenv('FORCE_LOCAL', 'False').lower() == 'true'

# Initialize the ADB tool
def get_adb_tool():
    """Get or create ADB tool instance"""
    return SQLiteADBQueryTool(
        package_name=PACKAGE_NAME,
        db_name=DB_NAME,
        force_local=FORCE_LOCAL,
        use_cache=USE_CACHE,
        device_serial=DEVICE_SERIAL
    )

@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')

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
            count = tool.get_table_count(table)
            table_info.append({
                'name': table,
                'row_count': count
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
            return jsonify({'success': False, 'error': 'Query execution failed'})

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
        import subprocess
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
            package_name=PACKAGE_NAME,
            db_name=DB_NAME,
            force_local=True,
            use_cache=True,
            force_pull=True,
            device_serial=DEVICE_SERIAL
        )

        # Pull fresh database
        if not tool_force.pull_database():
            return jsonify({'success': False, 'error': 'Failed to pull database from device'})

        # Fix gzip decompression issue
        cache_dir = Path(tempfile.gettempdir()) / "adb_sqlite_cache"
        db_file = cache_dir / f"{PACKAGE_NAME}_{DB_NAME}"

        if db_file.exists():
            # Check if file is gzipped
            result = subprocess.run(['file', str(db_file)], capture_output=True, text=True)
            if 'gzip compressed data' in result.stdout:
                print(f"🔧 Detected gzipped database, decompressing...")
                # Decompress the file
                gz_file = str(db_file) + '.gz'
                db_file.rename(gz_file)
                subprocess.run(['gunzip', gz_file], check=True)
                print(f"✅ Database decompressed successfully")

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
        import subprocess
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
        db_file = cache_dir / f"{PACKAGE_NAME}_{DB_NAME}"

        if db_file.exists():
            # Check if file is gzipped
            result = subprocess.run(['file', str(db_file)], capture_output=True, text=True)
            if 'gzip compressed data' in result.stdout:
                print(f"🔧 Detected gzipped database, decompressing...")
                # Decompress the file
                gz_file = str(db_file) + '.gz'
                db_file.rename(gz_file)
                subprocess.run(['gunzip', gz_file], check=True)
                print(f"✅ Database decompressed successfully")

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
