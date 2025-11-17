#!/bin/bash
# Fix gzip decompression issue in ADB SQLite cache

# Load environment variables from .env file
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Default values if not set in .env
PACKAGE_NAME=${PACKAGE_NAME:-com.winitsoftware.emiratessnacks}
DB_NAME=${DB_NAME:-master_data.db}

# Get cache directory dynamically
CACHE_DIR="${TMPDIR:-/tmp}/adb_sqlite_cache"
DB_FILE="$CACHE_DIR/${PACKAGE_NAME}_${DB_NAME}"

# Check if file exists
if [ ! -f "$DB_FILE" ]; then
    echo "Database file not found: $DB_FILE"
    exit 1
fi

# Check if file is gzipped
FILE_TYPE=$(file "$DB_FILE" | grep -o "gzip compressed data")

if [ -n "$FILE_TYPE" ]; then
    echo "Database is gzipped, decompressing..."
    mv "$DB_FILE" "$DB_FILE.gz"
    gunzip "$DB_FILE.gz"
    echo "✅ Database decompressed successfully"
    file "$DB_FILE"
else
    echo "✅ Database is already decompressed"
    file "$DB_FILE"
fi
