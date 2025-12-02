#!/usr/bin/env python3
"""
SQLite ADB Database Query Tool
Connects to SQLite database on Android device through ADB and executes queries.

PERFORMANCE OPTIMIZATION:
This tool automatically uses the most efficient method for each operation:

1. REMOTE EXECUTION (ALL QUERIES):
   - Uses direct on-device execution via `run-as` + `sqlite3`
   - Handles SELECT, PRAGMA, INSERT, UPDATE, DELETE directly on device
   - No database transfer required - much faster for large databases
   - Example: A 100MB database query executes in <1s instead of 30-60s
   - INSERT/UPDATE/DELETE queries execute instantly without pull-push cycle

2. FALLBACK (LOCAL EXECUTION):
   - If app is not debuggable (run-as fails), falls back to pull method
   - Pulls database to local temp file, executes query, pushes back
   - Use --force-local to always use this method

REQUIREMENTS:
- ADB installed and in PATH
- Android device connected with USB debugging enabled
- For remote execution: App must be debuggable (android:debuggable="true")
"""

import sys
import argparse
import subprocess
import json
import tempfile
import os
import shutil
from typing import Optional, List, Dict, Any, Tuple
import sqlite3
from pathlib import Path

# Set UTF-8 encoding for Windows
if sys.platform.startswith('win'):
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

class SQLiteADBQueryTool:
    def __init__(self, package_name: str = "com.winitsoftware.emiratessnacks", db_name: str = "master_data.db",
                 force_local: bool = False, use_cache: bool = True, force_pull: bool = False, user_id: Optional[int] = None,
                 device_serial: Optional[str] = None):
        """
        Initialize the SQLite ADB query tool.

        Args:
            package_name: Android package name
            db_name: SQLite database filename
            force_local: Force local execution (pull DB) even for read-only queries
            use_cache: Use cached database if available and not modified (default: True)
            force_pull: Force re-pull even if cache is valid (default: False)
            user_id: Android user ID for cloned apps (e.g., 95 for cloned app). If None, uses default user (0)
            device_serial: Specific device serial to use (e.g., '192.168.0.237:5000' for WiFi ADB)
        """
        self.package_name = package_name
        self.db_name = db_name
        self.local_db_path = None
        self.force_local = force_local
        self.use_cache = use_cache
        self.force_pull = force_pull
        self.user_id = user_id
        self.device_serial = device_serial
        self.run_as_supported = None  # Cache run-as support check
        self.last_error = None  # Store last error message for API responses

        # Setup cache directory
        self.cache_dir = Path(tempfile.gettempdir()) / "adb_sqlite_cache"
        self.cache_dir.mkdir(exist_ok=True)
        cache_suffix = f"_user{user_id}" if user_id else ""
        device_suffix = f"_{device_serial.replace(':', '_').replace('.', '_')}" if device_serial else ""
        self.cache_metadata_file = self.cache_dir / f"{package_name}_{db_name}{cache_suffix}{device_suffix}.json"

    def _get_run_as_cmd(self, command: str = "") -> str:
        """
        Construct run-as command with optional user flag.

        Args:
            command: Command to run after run-as (optional)

        Returns:
            str: Full run-as command string
        """
        user_flag = f" --user {self.user_id}" if self.user_id is not None else ""
        if command:
            return f"run-as {self.package_name}{user_flag} {command}"
        return f"run-as {self.package_name}{user_flag}"

    def _get_adb_cmd(self, cmd: List[str]) -> List[str]:
        """
        Construct ADB command with optional device serial.

        Args:
            cmd: Command arguments (without 'adb')

        Returns:
            List[str]: Full ADB command with device serial if specified
        """
        adb_cmd = ['adb']
        if self.device_serial:
            adb_cmd.extend(['-s', self.device_serial])
        adb_cmd.extend(cmd)
        return adb_cmd

    def check_adb_connection(self) -> bool:
        """
        Check if ADB is available and device is connected.

        Returns:
            bool: True if ADB is working, False otherwise
        """
        try:
            result = subprocess.run(['adb', 'devices'],
                                  capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                print("❌ ADB command failed. Make sure ADB is installed and in PATH.")
                return False

            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            connected_devices = [line for line in lines if line.strip() and 'device' in line]

            if not connected_devices:
                print("❌ No Android devices connected via ADB.")
                print("   Make sure USB debugging is enabled and device is connected.")
                return False

            # If specific device serial is specified, check if it's connected
            if self.device_serial:
                device_found = any(self.device_serial in device for device in connected_devices)
                if not device_found:
                    print(f"❌ Device {self.device_serial} not found.")
                    print(f"✅ Available devices:")
                    for device in connected_devices:
                        print(f"   {device}")
                    return False
                print(f"✅ Using device: {self.device_serial}")
            else:
                print(f"✅ Found {len(connected_devices)} connected device(s):")
                for device in connected_devices:
                    print(f"   {device}")
            return True

        except subprocess.TimeoutExpired:
            print("❌ ADB command timed out.")
            return False
        except FileNotFoundError:
            print("❌ ADB not found. Make sure Android SDK is installed and ADB is in PATH.")
            return False
    
    def check_database_exists(self) -> bool:
        """
        Check if the SQLite database exists on the device.

        Returns:
            bool: True if database exists, False otherwise
        """
        try:
            # Try multiple possible locations
            db_locations = [
                f"databases/{self.db_name}",
                f"files/{self.db_name}",
                f"files/SQLite/{self.db_name}"
            ]
            
            for db_path in db_locations:
                result = subprocess.run(self._get_adb_cmd(['shell', self._get_run_as_cmd(f'ls {db_path}')]),
                                      capture_output=True, text=True, timeout=10)

                if result.returncode == 0 and self.db_name in result.stdout:
                    print(f"✅ Database found at: {db_path}")
                    return True
            
            print(f"❌ Database not found in any expected location")
            return False
                
        except subprocess.TimeoutExpired:
            print("❌ ADB command timed out.")
            return False
    
    def find_database_path(self) -> Optional[str]:
        """
        Find the actual path of the database on the device.

        Returns:
            str: Database path if found, None otherwise
        """
        try:
            # Try multiple possible locations
            db_locations = [
                f"databases/{self.db_name}",
                f"files/{self.db_name}",
                f"files/SQLite/{self.db_name}"
            ]

            for db_path in db_locations:
                result = subprocess.run(self._get_adb_cmd(['shell', self._get_run_as_cmd(f'ls {db_path}')]),
                                      capture_output=True, text=True, timeout=10)

                if result.returncode == 0 and self.db_name in result.stdout:
                    return db_path

            return None

        except subprocess.TimeoutExpired:
            return None

    def get_remote_db_mtime(self) -> int:
        """
        Get the modification time of the database on the device.

        Returns:
            int: Unix timestamp of last modification, or 0 if error
        """
        try:
            db_path = self.find_database_path()
            if not db_path:
                return 0

            # Try to get modification time using stat
            result = subprocess.run(
                self._get_adb_cmd(['shell', self._get_run_as_cmd(f'stat -c %Y {db_path}')]),
                capture_output=True, text=True, timeout=5
            )

            if result.returncode == 0:
                return int(result.stdout.strip())

            # Fallback: Try ls -l and parse (less reliable but works on more devices)
            result = subprocess.run(
                self._get_adb_cmd(['shell', self._get_run_as_cmd(f'ls -l {db_path}')]),
                capture_output=True, text=True, timeout=5
            )

            if result.returncode == 0:
                # Parse ls output to get approximate timestamp
                # This is not as accurate but works as a cache invalidation check
                import hashlib
                return int(hashlib.md5(result.stdout.encode()).hexdigest()[:8], 16)

            return 0

        except Exception as e:
            print(f"⚠️  Could not get remote DB mtime: {e}")
            return 0

    def load_cache_metadata(self) -> Dict[str, Any]:
        """
        Load cache metadata from JSON file.

        Returns:
            dict: Cache metadata or empty dict if not found
        """
        if not self.cache_metadata_file.exists():
            return {}

        try:
            with open(self.cache_metadata_file, 'r') as f:
                return json.load(f)
        except Exception:
            return {}

    def save_cache_metadata(self, metadata: Dict[str, Any]):
        """
        Save cache metadata to JSON file.

        Args:
            metadata: Metadata dictionary to save
        """
        try:
            with open(self.cache_metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            print(f"⚠️  Could not save cache metadata: {e}")

    def get_cached_db_path(self) -> Optional[str]:
        """
        Get the path to the cached database if valid.

        Returns:
            str: Path to cached DB if valid, None otherwise
        """
        if not self.use_cache or self.force_pull:
            return None

        metadata = self.load_cache_metadata()
        if not metadata:
            return None

        cached_db_path = self.cache_dir / f"{self.package_name}_{self.db_name}"
        if not cached_db_path.exists():
            return None

        # Check if remote DB has been modified
        remote_mtime = self.get_remote_db_mtime()
        if remote_mtime == 0:
            # Can't determine mtime, use cache anyway
            print("⚠️  Cannot verify cache freshness, using cached database")
            return str(cached_db_path)

        cached_mtime = metadata.get('mtime', 0)
        if remote_mtime == cached_mtime:
            print(f"✅ Using cached database (last modified: {metadata.get('cached_at', 'unknown')})")
            return str(cached_db_path)

        print(f"📝 Remote database has been modified, will re-pull...")
        return None

    def ensure_sqlite3_on_device(self) -> Optional[str]:
        """
        Ensure sqlite3 binary is available on the device.
        Returns the path to sqlite3 if available, None otherwise.
        This method is smart and will automatically set up sqlite3 if found in system.

        Returns:
            str: Path to sqlite3 binary (relative or absolute), or None if unavailable
        """
        # First check if sqlite3 already exists in app directory
        result = subprocess.run(
            self._get_adb_cmd(['shell', self._get_run_as_cmd('./sqlite3 -version')]),
            capture_output=True, text=True, timeout=5
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0 and ('SQLite' in output or '3.' in output):
            print(f"✅ Using sqlite3 from app directory")
            return './sqlite3'

        # Check system locations
        system_paths = [
            '/system/bin/sqlite3',
            '/system/xbin/sqlite3',
            '/data/local/tmp/sqlite3'
        ]

        for path in system_paths:
            result = subprocess.run(
                self._get_adb_cmd(['shell', f'{path} -version 2>&1']),
                capture_output=True, text=True, timeout=5
            )
            output = (result.stdout + result.stderr).strip()
            
            if result.returncode == 0 and ('SQLite' in output or '3.' in output):
                print(f"✅ Found sqlite3 at: {path}")
                
                # Try to copy it to app directory for proper run-as access
                print(f"   Setting up sqlite3 in app directory...")
                copy_result = subprocess.run(
                    self._get_adb_cmd(['shell', self._get_run_as_cmd(f'cp {path} ./sqlite3')]),
                    capture_output=True, text=True, timeout=10
                )

                if copy_result.returncode == 0:
                    # Make it executable
                    subprocess.run(
                        self._get_adb_cmd(['shell', self._get_run_as_cmd('chmod 755 ./sqlite3')]),
                        capture_output=True, text=True, timeout=5
                    )

                    # Verify it works
                    verify = subprocess.run(
                        self._get_adb_cmd(['shell', self._get_run_as_cmd('./sqlite3 -version')]),
                        capture_output=True, text=True, timeout=5
                    )
                    if verify.returncode == 0:
                        print(f"✅ sqlite3 successfully set up in app directory")
                        return './sqlite3'
                else:
                    print(f"⚠️  Could not copy to app directory, using system path directly")
                    return path

        # sqlite3 not found in any location - try to push bundled binary
        bundled_sqlite3 = Path(__file__).parent / "sqlite3-arm64"
        if bundled_sqlite3.exists():
            print(f"📦 sqlite3 not found on device, pushing bundled binary...")
            try:
                # Push to /data/local/tmp/
                push_result = subprocess.run(
                    self._get_adb_cmd(['push', str(bundled_sqlite3), '/data/local/tmp/sqlite3']),
                    capture_output=True, text=True, timeout=30,
                    env={**os.environ, 'MSYS_NO_PATHCONV': '1'}  # Prevent path conversion on Windows Git Bash
                )

                if push_result.returncode == 0:
                    # Make it executable
                    subprocess.run(
                        self._get_adb_cmd(['shell', 'chmod 755 /data/local/tmp/sqlite3']),
                        capture_output=True, text=True, timeout=5
                    )

                    # Verify it works
                    verify = subprocess.run(
                        self._get_adb_cmd(['shell', '/data/local/tmp/sqlite3 -version']),
                        capture_output=True, text=True, timeout=5
                    )
                    output = (verify.stdout + verify.stderr).strip()

                    if verify.returncode == 0 and ('SQLite' in output or '3.' in output):
                        print(f"✅ Successfully pushed and installed sqlite3 on device")

                        # Now copy to app directory
                        print(f"   Setting up sqlite3 in app directory...")
                        copy_result = subprocess.run(
                            self._get_adb_cmd(['shell', self._get_run_as_cmd('cp /data/local/tmp/sqlite3 ./sqlite3')]),
                            capture_output=True, text=True, timeout=10
                        )

                        if copy_result.returncode == 0:
                            subprocess.run(
                                self._get_adb_cmd(['shell', self._get_run_as_cmd('chmod 755 ./sqlite3')]),
                                capture_output=True, text=True, timeout=5
                            )
                            print(f"✅ sqlite3 successfully set up in app directory")
                            return './sqlite3'
                        else:
                            print(f"⚠️  Could not copy to app directory, using /data/local/tmp/sqlite3")
                            return '/data/local/tmp/sqlite3'
                    else:
                        print(f"❌ Pushed sqlite3 binary but it failed to execute")
                        print(f"   Device architecture may be incompatible (bundled binary is arm64)")
                else:
                    print(f"❌ Failed to push sqlite3: {push_result.stderr}")
            except Exception as e:
                print(f"❌ Error pushing sqlite3: {e}")

        print("❌ sqlite3 not found and no bundled binary available")
        print("   The database pull will work, but remote queries won't be available")
        print("   You can still use: python adb_sqlite_query_tool.py --force-local")
        return None

    def check_run_as_support(self) -> bool:
        """
        Check if run-as command works for this package (app must be debuggable).
        Also ensures sqlite3 is available on the device.

        Returns:
            bool: True if run-as is supported and sqlite3 is available, False otherwise
        """
        if self.run_as_supported is not None:
            return self.run_as_supported

        try:
            db_path = self.find_database_path()
            if not db_path:
                self.run_as_supported = False
                return False

            # Try a simple test command
            result = subprocess.run(
                self._get_adb_cmd(['shell', self._get_run_as_cmd('echo "test"')]),
                capture_output=True, text=True, timeout=5
            )

            if result.returncode != 0:
                if "not debuggable" in result.stderr.lower() or "unknown package" in result.stderr.lower():
                    print("⚠️  run-as not supported (app not debuggable). Falling back to database pull method.")
                self.run_as_supported = False
                return False

            if "test" not in result.stdout:
                self.run_as_supported = False
                return False

            # Check if sqlite3 is available
            sqlite_path = self.ensure_sqlite3_on_device()
            if not sqlite_path:
                print("⚠️  Could not install sqlite3. Falling back to database pull method.")
                self.run_as_supported = False
                return False

            self.sqlite3_path = sqlite_path
            self.run_as_supported = True
            return True

        except Exception as e:
            print(f"⚠️  Could not check run-as support: {e}")
            self.run_as_supported = False
            return False

    def execute_remote_query(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """
        Execute a SQL query directly on the device using run-as + sqlite3.
        This is much faster for all queries as it avoids pulling the entire database.
        Supports both read (SELECT/PRAGMA) and write (INSERT/UPDATE/DELETE) operations.

        Args:
            query: SQL query to execute

        Returns:
            List of dictionaries containing query results, or None if error
        """
        self.last_error = None  # Clear previous error
        try:
            db_path = self.find_database_path()
            if not db_path:
                self.last_error = "Could not find database path on device"
                print(f"❌ {self.last_error}")
                return None

            # Use the sqlite3 path determined during initialization
            sqlite_path = getattr(self, 'sqlite3_path', './sqlite3')

            # Check if this is a write query
            is_write = self.is_write_query(query)

            # Escape the query for shell - handle both single and double quotes
            # Replace backslashes first, then quotes
            escaped_query = query.replace('\\', '\\\\')
            escaped_query = escaped_query.replace('"', '\\"')
            escaped_query = escaped_query.replace('$', '\\$')
            escaped_query = escaped_query.replace('`', '\\`')
            # Single quotes inside double quotes don't need escaping in most shells

            # Use JSON output mode for easier parsing (for SELECT queries)
            # For write queries, we just need to execute and check success
            if is_write:
                sqlite_cmd = f'{sqlite_path} {db_path} "{escaped_query}"'
            else:
                sqlite_cmd = f'{sqlite_path} {db_path} -json "{escaped_query}"'

            result = subprocess.run(
                self._get_adb_cmd(['shell', self._get_run_as_cmd(f'{sqlite_cmd}')]),
                capture_output=True, text=True, timeout=60
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip()
                if "not debuggable" in error_msg.lower():
                    print("⚠️  run-as not supported. Falling back to local execution.")
                    return None
                # Extract SQLite error message
                if "Error:" in error_msg:
                    self.last_error = error_msg.split("Error:")[-1].strip()
                elif "error" in error_msg.lower():
                    self.last_error = error_msg
                else:
                    self.last_error = error_msg or "Remote query execution failed"
                print(f"❌ Remote query failed: {self.last_error}")
                return None

            # For write queries, return empty list to indicate success
            if is_write:
                print(f"✅ Query executed successfully on device.")
                return []

            # Parse JSON output for SELECT queries
            output = result.stdout.strip()
            if not output:
                # Empty result set
                if query.strip().upper().startswith('SELECT') or query.strip().upper().startswith('PRAGMA'):
                    return []
                return None

            try:
                # Parse JSON array of objects
                results = json.loads(output)
                return results if isinstance(results, list) else []
            except json.JSONDecodeError:
                # Fallback: Try to parse as non-JSON output
                print("⚠️  Could not parse JSON output, trying non-JSON mode...")
                return self._execute_remote_query_fallback(query, db_path)

        except subprocess.TimeoutExpired:
            self.last_error = "Query timed out (exceeded 60 seconds)"
            print(f"❌ {self.last_error}")
            return None
        except Exception as e:
            self.last_error = f"Error executing remote query: {e}"
            print(f"❌ {self.last_error}")
            return None

    def _execute_remote_query_fallback(self, query: str, db_path: str) -> Optional[List[Dict[str, Any]]]:
        """
        Fallback method for remote query execution when JSON mode is not available.
        Uses column headers and pipe-separated output.

        Args:
            query: SQL query to execute
            db_path: Database path on device

        Returns:
            List of dictionaries, or None if error
        """
        try:
            # Use the sqlite3 path determined during initialization
            sqlite_path = getattr(self, 'sqlite3_path', './sqlite3')

            # Escape the query for shell - handle special characters
            escaped_query = query.replace('\\', '\\\\')
            escaped_query = escaped_query.replace('"', '\\"')
            escaped_query = escaped_query.replace('$', '\\$')
            escaped_query = escaped_query.replace('`', '\\`')

            # Use -header and -separator modes
            sqlite_cmd = f'{sqlite_path} {db_path} -header -separator "|" "{escaped_query}"'

            result = subprocess.run(
                self._get_adb_cmd(['shell', self._get_run_as_cmd(f'{sqlite_cmd}')]),
                capture_output=True, text=True, timeout=60
            )

            if result.returncode != 0:
                return None

            lines = result.stdout.strip().split('\n')
            if not lines:
                return []

            # First line is headers
            headers = [h.strip() for h in lines[0].split('|')]

            # Remaining lines are data
            results = []
            for line in lines[1:]:
                if not line.strip():
                    continue
                values = [v.strip() for v in line.split('|')]
                if len(values) == len(headers):
                    row_dict = dict(zip(headers, values))
                    results.append(row_dict)

            return results

        except Exception as e:
            print(f"❌ Fallback remote query failed: {e}")
            return None

    def is_write_query(self, query: str) -> bool:
        """
        Check if a query is a write operation (INSERT/UPDATE/DELETE).

        Args:
            query: SQL query to check

        Returns:
            bool: True if write query, False otherwise
        """
        query_upper = query.strip().upper()
        write_operations = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 'REPLACE']
        return any(query_upper.startswith(op) for op in write_operations)

    def pull_database(self, use_compression: bool = True) -> bool:
        """
        Pull the database from device to local file, with optional caching and compression.

        Args:
            use_compression: Use gzip compression during transfer (default: True)

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check for cached database first
            cached_path = self.get_cached_db_path()
            if cached_path:
                self.local_db_path = cached_path
                self.device_db_path = self.find_database_path()  # Store for push operation
                return True

            # Find the database path
            db_path = self.find_database_path()
            if not db_path:
                print("❌ Could not find database on device")
                return False

            self.device_db_path = db_path  # Store for push operation

            # Determine where to save the database
            if self.use_cache:
                # Save to cache directory
                cached_db_path = self.cache_dir / f"{self.package_name}_{self.db_name}"
                self.local_db_path = str(cached_db_path)
            else:
                # Create temporary file
                temp_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
                self.local_db_path = temp_file.name
                temp_file.close()

            print(f"📥 Pulling database from device...")
            print(f"   Source: {db_path}")
            print(f"   Destination: {self.local_db_path}")

            # Determine transfer method
            if use_compression:
                # Option 4: Use compressed transfer
                success = self._pull_database_compressed(db_path)
            else:
                # Standard transfer
                success = self._pull_database_standard(db_path)

            if success:
                # Also pull WAL and SHM files if they exist (for uncommitted transactions)
                self._pull_wal_files(db_path)

                # Save cache metadata
                if self.use_cache:
                    remote_mtime = self.get_remote_db_mtime()
                    from datetime import datetime
                    metadata = {
                        'mtime': remote_mtime,
                        'cached_at': datetime.now().isoformat(),
                        'db_path': db_path,
                        'package': self.package_name
                    }
                    self.save_cache_metadata(metadata)

                file_size = os.path.getsize(self.local_db_path)
                print(f"✅ Database pulled successfully ({file_size:,} bytes)")
                return True

            return False

        except Exception as e:
            print(f"❌ Error pulling database: {e}")
            return False

    def _pull_wal_files(self, db_path: str) -> None:
        """
        Pull WAL and SHM files if they exist (for uncommitted transactions).
        This ensures we get all data including uncommitted changes.

        Args:
            db_path: Database path on device
        """
        try:
            wal_path = f"{db_path}-wal"
            shm_path = f"{db_path}-shm"

            # Check if WAL file exists
            check_wal = subprocess.run(
                self._get_adb_cmd(['shell', self._get_run_as_cmd(f'ls {wal_path}')]),
                capture_output=True, text=True, timeout=5
            )

            if check_wal.returncode == 0 and '-wal' in check_wal.stdout:
                print(f"   Found WAL file, pulling to include uncommitted data...")
                local_wal_path = f"{self.local_db_path}-wal"

                # Pull WAL file
                result = subprocess.run(
                    self._get_adb_cmd(['exec-out', self._get_run_as_cmd(f'cat {wal_path}')]),
                    capture_output=True, timeout=60
                )

                if result.returncode == 0:
                    with open(local_wal_path, 'wb') as f:
                        f.write(result.stdout)
                    wal_size = os.path.getsize(local_wal_path)
                    print(f"   ✅ WAL file pulled ({wal_size:,} bytes)")

                # Pull SHM file if exists
                check_shm = subprocess.run(
                    self._get_adb_cmd(['shell', self._get_run_as_cmd(f'ls {shm_path}')]),
                    capture_output=True, text=True, timeout=5
                )

                if check_shm.returncode == 0 and '-shm' in check_shm.stdout:
                    local_shm_path = f"{self.local_db_path}-shm"
                    result = subprocess.run(
                        self._get_adb_cmd(['exec-out', self._get_run_as_cmd(f'cat {shm_path}')]),
                        capture_output=True, timeout=60
                    )

                    if result.returncode == 0:
                        with open(local_shm_path, 'wb') as f:
                            f.write(result.stdout)
                        print(f"   ✅ SHM file pulled")

        except Exception as e:
            print(f"   ⚠️  Could not pull WAL files (non-critical): {e}")

    def _pull_database_standard(self, db_path: str) -> bool:
        """
        Pull database using standard cat method (no compression).

        Args:
            db_path: Database path on device

        Returns:
            bool: True if successful
        """
        try:
            print(f"   Transfer method: Standard (uncompressed)")
            result = subprocess.run(
                self._get_adb_cmd(['exec-out', self._get_run_as_cmd(f'cat {db_path}')]),
                capture_output=True, timeout=300)

            if result.returncode == 0:
                with open(self.local_db_path, 'wb') as f:
                    f.write(result.stdout)
                return True
            else:
                print(f"❌ Failed to pull database: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            print("❌ Transfer timed out")
            return False

    def _pull_database_compressed(self, db_path: str) -> bool:
        """
        Pull database using gzip compression for faster transfer.

        Args:
            db_path: Database path on device

        Returns:
            bool: True if successful
        """
        try:
            # Check if gzip is available on device
            check_gzip = subprocess.run(
                self._get_adb_cmd(['shell', 'which gzip']),
                capture_output=True, text=True, timeout=5
            )

            if check_gzip.returncode != 0 or not check_gzip.stdout.strip():
                print(f"   Transfer method: Standard (gzip not available on device)")
                return self._pull_database_standard(db_path)

            print(f"   Transfer method: Compressed (gzip)")
            import time
            start_time = time.time()

            # Pull compressed data
            result = subprocess.run(
                self._get_adb_cmd(['exec-out', self._get_run_as_cmd(f'gzip -c {db_path}')]),
                capture_output=True, timeout=300)

            if result.returncode != 0:
                print(f"⚠️  Compression failed, falling back to standard transfer")
                return self._pull_database_standard(db_path)

            # Write compressed data to temp file
            compressed_path = self.local_db_path + '.gz'
            with open(compressed_path, 'wb') as f:
                f.write(result.stdout)

            compressed_size = os.path.getsize(compressed_path)
            transfer_time = time.time() - start_time

            # Decompress
            print(f"   Decompressing ({compressed_size:,} bytes transferred in {transfer_time:.1f}s)...")
            try:
                import gzip
                with gzip.open(compressed_path, 'rb') as f_in, open(self.local_db_path, 'wb') as f_out:
                    f_out.write(f_in.read())
                os.unlink(compressed_path) # Clean up compressed file
            except Exception as e:
                print(f"❌ Decompression failed: {e}")
                if os.path.exists(compressed_path):
                    os.unlink(compressed_path)
                return False

            # gzip -d removes the .gz extension automatically
            if not os.path.exists(self.local_db_path):
                print(f"❌ Decompressed file not found")
                return False

            return True

        except subprocess.TimeoutExpired:
            print("❌ Transfer timed out")
            return False
        except Exception as e:
            print(f"⚠️  Compression error: {e}, falling back to standard transfer")
            return self._pull_database_standard(db_path)
    
    def push_database(self) -> bool:
        """
        Push the modified database back to the Android device.
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.local_db_path or not os.path.exists(self.local_db_path):
            print("❌ No local database file to push.")
            return False
        
        if not hasattr(self, 'device_db_path') or not self.device_db_path:
            print("❌ Device database path not known. Pull database first.")
            return False
        
        try:
            print(f"📤 Pushing database back to device...")
            print(f"   Source: {self.local_db_path}")
            print(f"   Destination: {self.device_db_path}")
            
            # First, push to a temporary location accessible by shell
            temp_path = f"/data/local/tmp/{self.db_name}"

            # Push to temp location
            result = subprocess.run(
                self._get_adb_cmd(['push', self.local_db_path, temp_path]),
                capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                print(f"❌ Failed to push to temp location: {result.stderr}")
                return False

            # Copy from temp to app's private directory with proper permissions
            result = subprocess.run(
                self._get_adb_cmd(['shell', self._get_run_as_cmd(f'cp {temp_path} {self.device_db_path}')]),
                capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                print(f"❌ Failed to copy to app directory: {result.stderr}")
                # Clean up temp file
                subprocess.run(self._get_adb_cmd(['shell', f'rm {temp_path}']), capture_output=True)
                return False

            # Clean up temp file
            subprocess.run(self._get_adb_cmd(['shell', f'rm {temp_path}']), capture_output=True)
            
            print(f"✅ Database pushed successfully")
            return True
            
        except subprocess.TimeoutExpired:
            print("❌ ADB command timed out.")
            return False
        except Exception as e:
            print(f"❌ Error pushing database: {e}")
            return False
    
    def get_table_list(self) -> List[str]:
        """
        Get list of all tables in the database.
        
        Returns:
            List of table names
        """
        query = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        results = self.execute_query(query)
        
        if results:
            return [row['name'] for row in results]
        return []
    
    def get_table_info(self, table_name: str) -> List[Dict[str, Any]]:
        """
        Get detailed information about a table structure.
        
        Args:
            table_name: Name of the table
            
        Returns:
            List of column information dictionaries
        """
        query = f"PRAGMA table_info({table_name});"
        return self.execute_query(query) or []
    
    def get_table_count(self, table_name: str) -> int:
        """
        Get row count for a table.
        
        Args:
            table_name: Name of the table
            
        Returns:
            Number of rows in the table
        """
        query = f"SELECT COUNT(*) as count FROM {table_name};"
        results = self.execute_query(query)
        
        if results:
            return results[0]['count']
        return 0
    
    def execute_query(self, query: str, limit: Optional[int] = None, prefer_remote: bool = True) -> Optional[List[Dict[str, Any]]]:
        """
        Execute a SQL query with automatic method selection (remote vs local).

        For all queries (SELECT/PRAGMA/INSERT/UPDATE/DELETE), attempts remote execution first if supported.
        Falls back to local execution (pull → modify → push) only if remote fails.

        Args:
            query: SQL query to execute
            limit: Optional limit for SELECT queries
            prefer_remote: Try remote execution first (default: True)

        Returns:
            List of dictionaries containing query results, or None if error
        """
        # Add LIMIT clause if specified
        if limit and 'LIMIT' not in query.upper() and query.strip().upper().startswith('SELECT'):
            query = f"{query.rstrip(';')} LIMIT {limit};"

        # Try remote execution first if not forced to use local
        if prefer_remote and not self.force_local:
            if self.check_run_as_support():
                print("🚀 Using fast remote query execution...")
                results = self.execute_remote_query(query)
                if results is not None:
                    return results
                print("⚠️  Remote execution failed, falling back to local...")

        # Fall back to local execution
        return self.execute_query_local(query)

    def execute_query_local(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """
        Execute a SQL query on the local database copy.
        Automatically pulls the database if not already available.

        Args:
            query: SQL query to execute

        Returns:
            List of dictionaries containing query results, or None if error
        """
        self.last_error = None  # Clear previous error
        if not self.local_db_path or not os.path.exists(self.local_db_path):
            print("📥 Pulling database for local execution...")
            if not self.pull_database():
                self.last_error = "Failed to pull database for local execution"
                print(f"❌ {self.last_error}")
                return None

        try:
            conn = sqlite3.connect(self.local_db_path)
            conn.row_factory = sqlite3.Row  # Enable dict-like access
            cursor = conn.cursor()

            cursor.execute(query)

            if query.strip().upper().startswith('SELECT') or query.strip().upper().startswith('PRAGMA'):
                results = cursor.fetchall()
                # Convert to list of dictionaries
                return [dict(row) for row in results]
            else:
                conn.commit()
                affected_rows = cursor.rowcount
                print(f"✅ Query executed successfully. {affected_rows} rows affected.")

                # Automatically push changes back for write queries
                if self.is_write_query(query):
                    print("📤 Pushing changes back to device...")
                    if self.push_database():
                        print("✅ Changes synced to device")
                    else:
                        print("⚠️  Warning: Changes were not synced to device. You may need to restart the app.")

                return []  # Return empty list to indicate success

        except sqlite3.Error as e:
            self.last_error = str(e)
            print(f"❌ SQLite error: {self.last_error}")
            return None
        finally:
            if 'conn' in locals():
                conn.close()
    
    def cleanup(self):
        """Clean up temporary database file (but preserve cache)."""
        if self.local_db_path and os.path.exists(self.local_db_path):
            # Don't delete cached databases
            if self.use_cache and str(self.cache_dir) in self.local_db_path:
                print("💾 Database cached for future use")
                return

            try:
                os.unlink(self.local_db_path)
                print("🧹 Temporary database file cleaned up")
            except Exception as e:
                print(f"⚠️  Warning: Could not clean up temporary file: {e}")

    def clear_cache(self):
        """Clear the database cache."""
        try:
            if self.cache_metadata_file.exists():
                os.unlink(self.cache_metadata_file)

            cached_db_path = self.cache_dir / f"{self.package_name}_{self.db_name}"
            if cached_db_path.exists():
                os.unlink(cached_db_path)

            print("🧹 Cache cleared successfully")
            return True
        except Exception as e:
            print(f"❌ Error clearing cache: {e}")
            return False
    
    def print_table_data(self, table_name: str, limit: int = 20, offset: int = 0):
        """
        Print formatted table data.
        
        Args:
            table_name: Name of the table
            limit: Number of rows to display
            offset: Number of rows to skip
        """
        # Get table structure
        columns = self.get_table_info(table_name)
        if not columns:
            print(f"❌ Could not get table structure for {table_name}")
            return
        
        # Get data
        query = f"SELECT * FROM {table_name} LIMIT {limit} OFFSET {offset};"
        data = self.execute_query(query)
        
        if data is None:
            print(f"❌ Could not fetch data from {table_name}")
            return
        
        if not data:
            print(f"📭 No data found in table {table_name}")
            return
        
        # Print table header
        print(f"\n📊 Table: {table_name}")
        print(f"📈 Showing {len(data)} rows (offset: {offset})")
        print("=" * 80)
        
        # Print column headers
        headers = [col['name'] for col in columns]
        header_str = " | ".join(f"{h:<15}" for h in headers)
        print(header_str)
        print("-" * len(header_str))
        
        # Print data rows
        for row in data:
            row_str = " | ".join(f"{str(row.get(h, '')):<15}" for h in headers)
            print(row_str)
        
        print("=" * 80)
    
    def export_to_csv(self, table_name: str, output_file: str, limit: Optional[int] = None):
        """
        Export table data to CSV file.
        
        Args:
            table_name: Name of the table
            output_file: Output CSV file path
            limit: Optional row limit
        """
        import csv
        
        # Get table structure
        columns = self.get_table_info(table_name)
        if not columns:
            print(f"❌ Could not get table structure for {table_name}")
            return
        
        # Get data
        query = f"SELECT * FROM {table_name}"
        if limit:
            query += f" LIMIT {limit}"
        query += ";"
        
        data = self.execute_query(query)
        
        if data is None:
            print(f"❌ Could not fetch data from {table_name}")
            return
        
        try:
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = [col['name'] for col in columns]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for row in data:
                    writer.writerow(row)
            
            print(f"✅ Exported {len(data)} rows to {output_file}")
            
        except Exception as e:
            print(f"❌ Error exporting to CSV: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="SQLite ADB Database Query Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all tables (uses fast remote execution by default)
  python adb_sqlite_query_tool.py --list-tables

  # Show table structure
  python adb_sqlite_query_tool.py --table-info users

  # Execute custom query (automatically uses remote execution for SELECT)
  python adb_sqlite_query_tool.py --query "SELECT * FROM users LIMIT 5"

  # Write query (automatically executes directly on device via remote execution)
  python adb_sqlite_query_tool.py --query "UPDATE users SET active=1 WHERE id=5"

  # Force re-pull database even if cached version is available
  python adb_sqlite_query_tool.py --query "SELECT * FROM users" --force-pull

  # Disable caching (always pull fresh copy)
  python adb_sqlite_query_tool.py --list-tables --no-cache

  # Clear cached database
  python adb_sqlite_query_tool.py --clear-cache

  # Disable compression during transfer
  python adb_sqlite_query_tool.py --export users --no-compression

Performance Features:
  1. REMOTE EXECUTION (Fastest):
     - ALL queries (SELECT/INSERT/UPDATE/DELETE) execute directly on device via run-as + sqlite3
     - No database transfer required (executes in <1 second typically)
     - Requires debuggable app

  2. DATABASE CACHING:
     - Database is cached locally after first pull
     - Subsequent queries check modification time and reuse cache if unchanged
     - Saves 10-30 seconds on repeated queries
     - Use --force-pull to refresh cache

  3. COMPRESSED TRANSFER (Option 4):
     - Uses gzip compression during database transfer
     - Reduces 100 MB → 10-20 MB (typical)
     - Saves 50-70% transfer time
     - Automatically falls back if gzip unavailable on device
     - Use --no-compression to disable

  Cache Location: {tempdir}/adb_sqlite_cache/

Notes:
  - Remote execution requires debuggable app (most debug builds)
  - Use --force-local to always pull DB (slower but more compatible)
  - Cache is preserved between runs for faster subsequent queries
        """.format(tempdir=tempfile.gettempdir())
    )
    
    parser.add_argument('--package', default='com.winitsoftware.emiratessnacks',
                       help='Android package name (default: com.winitsoftware.emiratessnacks)')
    parser.add_argument('--db-name', default='master_data.db',
                       help='Database filename (default: master_data.db)')
    parser.add_argument('--user', type=int, metavar='USER_ID',
                       help='Android user ID for cloned apps (e.g., 95 for cloned app)')
    parser.add_argument('--device', '-s', metavar='SERIAL',
                       help='Device serial number (e.g., 192.168.0.237:5000 for WiFi ADB)')

    # Action arguments
    parser.add_argument('--list-tables', action='store_true',
                       help='List all tables in the database')
    parser.add_argument('--table-info', metavar='TABLE',
                       help='Show table structure')
    parser.add_argument('--query', metavar='SQL',
                       help='Execute custom SQL query')
    parser.add_argument('--show-table', metavar='TABLE',
                       help='Show table data')
    parser.add_argument('--export', metavar='TABLE',
                       help='Export table to CSV')
    parser.add_argument('--output', metavar='FILE',
                       help='Output file for export (default: table_name.csv)')
    parser.add_argument('--limit', type=int, default=20,
                       help='Row limit for queries (default: 20)')
    parser.add_argument('--offset', type=int, default=0,
                       help='Row offset for queries (default: 0)')
    parser.add_argument('--push', action='store_true',
                       help='Push modified database back to device after query execution')
    parser.add_argument('--force-local', action='store_true',
                       help='Force local execution (pull DB) even for read-only queries')
    parser.add_argument('--no-cache', action='store_true',
                       help='Disable database caching (always pull fresh copy)')
    parser.add_argument('--force-pull', action='store_true',
                       help='Force re-pull database even if cache is valid')
    parser.add_argument('--no-compression', action='store_true',
                       help='Disable gzip compression during transfer')
    parser.add_argument('--clear-cache', action='store_true',
                       help='Clear the database cache and exit')
    
    args = parser.parse_args()

    # Initialize tool
    tool = SQLiteADBQueryTool(
        args.package,
        args.db_name,
        force_local=args.force_local,
        use_cache=not args.no_cache,
        force_pull=args.force_pull,
        user_id=args.user,
        device_serial=args.device
    )

    try:
        # Handle --clear-cache flag
        if args.clear_cache:
            tool.clear_cache()
            sys.exit(0)

        # Check ADB connection
        if not tool.check_adb_connection():
            sys.exit(1)

        # Check if database exists
        if not tool.check_database_exists():
            print(f"❌ Database not found. Make sure the app is installed and has been run at least once.")
            sys.exit(1)

        # Determine if we need to pull the database
        # Only pull for: exports or when forced (remote execution handles write queries now)
        needs_pull = (
            args.export or
            args.force_local or
            args.force_pull
        )

        # If not using remote execution, pull the database
        if needs_pull or not tool.check_run_as_support():
            if not tool.pull_database(use_compression=not args.no_compression):
                sys.exit(1)

        # Execute requested action
        if args.list_tables:
            print("\n📋 Available Tables:")
            print("=" * 40)
            tables = tool.get_table_list()
            for table in tables:
                count = tool.get_table_count(table)
                print(f"  {table:<30} ({count:,} rows)")
        
        elif args.table_info:
            print(f"\n📋 Table Structure: {args.table_info}")
            print("=" * 60)
            columns = tool.get_table_info(args.table_info)
            if columns:
                print(f"{'Column':<20} {'Type':<15} {'Nullable':<10} {'Primary Key':<12}")
                print("-" * 60)
                for col in columns:
                    nullable = "YES" if col['notnull'] == 0 else "NO"
                    pk = "YES" if col['pk'] == 1 else "NO"
                    print(f"{col['name']:<20} {col['type']:<15} {nullable:<10} {pk:<12}")
            else:
                print(f"❌ Table '{args.table_info}' not found")
        
        elif args.query:
            print(f"\n🔍 Executing Query:")
            print(f"SQL: {args.query}")
            print("=" * 60)
            results = tool.execute_query(args.query, args.limit)
            if results is not None:
                if results:
                    # Print results in table format
                    headers = list(results[0].keys())
                    header_str = " | ".join(f"{h:<15}" for h in headers)
                    print(header_str)
                    print("-" * len(header_str))
                    for row in results:
                        row_str = " | ".join(f"{str(row.get(h, '')):<15}" for h in headers)
                        print(row_str)
                    print(f"\n📊 Total rows: {len(results)}")
                else:
                    print("📭 No results returned")
        
        elif args.show_table:
            tool.print_table_data(args.show_table, args.limit, args.offset)
        
        elif args.export:
            output_file = args.output or f"{args.export}.csv"
            tool.export_to_csv(args.export, output_file, args.limit)
        
        else:
            # Default: show database overview
            print("\n📊 Database Overview")
            print("=" * 40)
            tables = tool.get_table_list()
            print(f"Total tables: {len(tables)}")
            
            if tables:
                print("\n📋 Tables with row counts:")
                for table in tables:
                    count = tool.get_table_count(table)
                    print(f"  {table:<30} ({count:,} rows)")
        
        # Note: --push flag is deprecated as write queries now execute directly on device via remote execution
        # Kept for backwards compatibility but does nothing when remote execution is available
        if args.push and args.query and tool.local_db_path:
            # Only push if we actually pulled the database (fallback mode)
            if tool.push_database():
                print("\n✅ Changes have been pushed back to the device")
            else:
                print("\n❌ Failed to push changes back to the device")
    
    except KeyboardInterrupt:
        print("\n\n⏹️  Operation cancelled by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
    finally:
        tool.cleanup()

if __name__ == "__main__":
    main() 