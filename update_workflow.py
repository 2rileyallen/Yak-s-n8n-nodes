#!/usr/bin/env python3
import json
import sqlite3
import sys
import os
from datetime import datetime

# --- Configuration ---

# Node names that will be protected if a node's name STARTS WITH one of these.
PROTECTED_NODE_PREFIXES = {"File Path", "Local Path", "MyMachineConfig", "Personal Settings"}

# --- Configuration for protecting specific node parameters ---
# Node type for an HTTP Request node
HTTP_NODE_TYPE = "n8n-nodes-base.httpRequest"
# The specific URL that triggers the API key protection
PROTECTED_URL = "http://localhost:5678/api/v1/workflows"
# The name of the header containing the API key to preserve
API_KEY_HEADER_NAME = "X-N8N-API-KEY"


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
    """
    Merge new nodes into the existing node list, preserving protected nodes
    and specific parameters within certain nodes (e.g., API keys).
    """
    existing_by_name = {node.get("name", ""): node for node in existing_nodes}
    existing_by_id = {node.get("id", ""): node for node in existing_nodes}
    
    result_nodes = []
    new_node_names = {node.get("name", "") for node in new_nodes}

    # Helper function to check if a name has a protected prefix
    def is_protected(name):
        for prefix in PROTECTED_NODE_PREFIXES:
            if name.startswith(prefix):
                return True
        return False

    for new_node in new_nodes:
        node_name = new_node.get("name", "")

        # 1. Preserve entire nodes if their name starts with a protected prefix
        if is_protected(node_name) and node_name in existing_by_name:
            result_nodes.append(existing_by_name[node_name])
            log(f"[PROTECT] Preserved protected node by prefix: '{node_name}'")
            continue

        # 2. Check for specific parameter preservation (HTTP node API key)
        node_to_add = new_node
        
        is_http_node = node_to_add.get("type") == HTTP_NODE_TYPE
        has_protected_url = node_to_add.get("parameters", {}).get("url") == PROTECTED_URL

        if is_http_node and has_protected_url:
            old_node = existing_by_id.get(new_node.get("id"))
            if old_node:
                try:
                    # Find the old API key from the database version of the node
                    old_api_key_value = None
                    old_headers = old_node.get("parameters", {}).get("headerParameters", {}).get("parameters", [])
                    for header in old_headers:
                        if header.get("name") == API_KEY_HEADER_NAME:
                            old_api_key_value = header.get("value")
                            break
                    
                    # If an old key was found, update the new node with it
                    if old_api_key_value is not None:
                        new_headers = node_to_add.get("parameters", {}).get("headerParameters", {}).get("parameters", [])
                        for header in new_headers:
                            if header.get("name") == API_KEY_HEADER_NAME:
                                header["value"] = old_api_key_value
                                log(f"[PROTECT] Preserved API key in HTTP node: '{node_name}'")
                                break
                except Exception as e:
                    log(f"[WARNING] Could not process API key preservation for node '{node_name}': {e}")
        
        result_nodes.append(node_to_add)

    # 3. Add back any orphaned protected nodes from the old workflow
    for name, node in existing_by_name.items():
        if is_protected(name) and name not in new_node_names:
            result_nodes.append(node)
            log(f"[PROTECT] Preserved orphaned protected node: '{name}'")
            
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

