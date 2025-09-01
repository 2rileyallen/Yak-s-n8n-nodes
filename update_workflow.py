#!/usr/bin/env python3
import json
import sqlite3
import sys
import os
from datetime import datetime

# Protected node names that will never be overwritten during sync
PROTECTED_NODE_NAMES = {"File Path", "Local Path", "MyMachineConfig", "Personal Settings"}

def log(message):
    """Log with timestamp"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

def has_running_executions(cursor, workflow_id):
    """Check if workflow has any genuinely active executions (not stale records)"""
    try:
        cursor.execute("""
            SELECT COUNT(*) 
            FROM execution_entity 
            WHERE workflowId = ? 
              AND finished = 0
              AND stoppedAt IS NULL
        """, (workflow_id,))
        return cursor.fetchone()[0] > 0
    except Exception:
        return False

def create_backup_table_if_needed(cursor):
    """Create backup table if it doesn't exist"""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workflow_backups (
            backup_id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_workflow_id VARCHAR,
            backup_timestamp DATETIME,
            name VARCHAR,
            nodes TEXT,
            connections TEXT,
            settings TEXT,
            active BOOLEAN,
            createdAt DATETIME,
            updatedAt DATETIME
        )
    """)

def backup_workflow(cursor, workflow_id):
    """Backup workflow before updating"""
    cursor.execute("""
        INSERT INTO workflow_backups 
        SELECT 
            NULL,
            id,
            datetime('now'),
            name, nodes, connections, settings, active, createdAt, updatedAt
        FROM workflow_entity 
        WHERE id = ?
    """, (workflow_id,))
    log(f"[BACKUP] Backed up workflow {workflow_id}")

def merge_nodes(existing_nodes, new_nodes):
    """Preserve nodes with protected names from existing workflow"""
    existing_lookup = {node.get("name", ""): node for node in existing_nodes}
    result_nodes = []

    for node in new_nodes:
        node_name = node.get("name", "")
        if node_name in PROTECTED_NODE_NAMES and node_name in existing_lookup:
            result_nodes.append(existing_lookup[node_name])
            log(f"[PROTECT] Preserved protected node: {node_name}")
        else:
            result_nodes.append(node)

    # Add any protected nodes missing in new_nodes
    for existing_node in existing_nodes:
        existing_name = existing_node.get("name", "")
        if existing_name in PROTECTED_NODE_NAMES and not any(n.get("name") == existing_name for n in new_nodes):
            result_nodes.append(existing_node)
            log(f"[PROTECT] Preserved orphaned protected node: {existing_name}")

    return result_nodes

def find_workflow_by_name(cursor, workflow_name):
    """Find workflow by name"""
    cursor.execute("""
        SELECT id, active, nodes, connections 
        FROM workflow_entity 
        WHERE name = ?
    """, (workflow_name,))
    row = cursor.fetchone()
    if not row:
        return None, None, [], {}

    workflow_id, is_active, nodes_json, connections_json = row
    try:
        existing_nodes = json.loads(nodes_json) if nodes_json else []
        existing_connections = json.loads(connections_json) if connections_json else {}
    except Exception:
        existing_nodes, existing_connections = [], {}

    return workflow_id, is_active, existing_nodes, existing_connections

def update_workflow_safe(db_path, json_file_path):
    """Safely update workflow"""
    try:
        with open(json_file_path, "r", encoding="utf-8") as f:
            workflow_data = json.load(f)
        log(f"[LOAD] Loaded workflow JSON from: {json_file_path}")

        # Handle wrapper : {"nextCursor":..., "data":{...}}
        if "data" in workflow_data and isinstance(workflow_data["data"], dict):
            workflow_data = workflow_data["data"]

    except Exception as e:
        log(f"[ERROR] Failed to read JSON file: {e}")
        return False

    workflow_name = workflow_data.get("name", "Unknown")
    new_nodes = workflow_data.get("nodes", [])
    new_connections = workflow_data.get("connections", {})
    new_settings = workflow_data.get("settings", {})

    log(f"[PROCESS] Processing workflow: '{workflow_name}'")

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        create_backup_table_if_needed(cursor)

        workflow_id, is_active, existing_nodes, existing_connections = find_workflow_by_name(cursor, workflow_name)

        if not workflow_id:
            log(f"[SKIP] Workflow '{workflow_name}' not found in database - skipping")
            return False

        log(f"[FOUND] Found workflow ID: {workflow_id} (active: {is_active})")

        if has_running_executions(cursor, workflow_id):
            log(f"[SKIP] Workflow {workflow_id} has running executions - skipping update")
            return False

        backup_workflow(cursor, workflow_id)

        merged_nodes = merge_nodes(existing_nodes, new_nodes)

        cursor.execute("""
            UPDATE workflow_entity 
            SET nodes = ?, connections = ?, settings = ?, updatedAt = datetime('now')
            WHERE id = ?
        """, (json.dumps(merged_nodes), json.dumps(new_connections), json.dumps(new_settings), workflow_id))

        conn.commit()
        log(f"[SUCCESS] Updated workflow '{workflow_name}' (ID: {workflow_id})")
        return True

    except Exception as e:
        log(f"[ERROR] Database error: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn: 
            conn.close()

def main():
    # Debug: show exactly what arguments Python received
    log(f"[DEBUG] sys.argv = {sys.argv}")
    
    if len(sys.argv) != 3:
        log("[ERROR] Usage: python update_workflow.py <db_path> <json_file_path>")
        sys.exit(0)

    db_path, json_file_path = sys.argv[1], sys.argv[2]

    if not os.path.exists(db_path):
        log(f"[ERROR] Database not found: {db_path}")
        sys.exit(0)

    if not os.path.exists(json_file_path):
        log(f"[ERROR] JSON file not found: {json_file_path}")
        sys.exit(0)

    log("[START] Starting workflow update...")
    log(f"[INFO] Database: {db_path}")
    log(f"[INFO] JSON file: {json_file_path}")

    success = update_workflow_safe(db_path, json_file_path)

    try:
        os.remove(json_file_path)
        log(f"[CLEANUP] Cleaned up temp file: {json_file_path}")
    except Exception:
        pass

    if success:
        log("[SUCCESS] Workflow update completed successfully")
    else:
        log("[FAILED] Workflow update failed")

    # Always exit 0 so n8n doesn't treat as error
    sys.exit(0)

if __name__ == "__main__":
    main()