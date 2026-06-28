#!/usr/bin/env python3
import sys
import json
import subprocess
import os

SVM_CMD = os.environ.get("SVM_CMD", "svm")


def json_rpc(id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id}
    if error:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _svm(args):
    try:
        r = subprocess.run([SVM_CMD, "--json"] + args, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr.strip() or r.stdout.strip()}
        out = r.stdout.strip()
        if out:
            return json.loads(out)
        return {"ok": True, "output": ""}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def handle_request(msg):
    rid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params", {})

    if method == "initialize":
        json_rpc(rid, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "svm-mcp", "version": "1.0.0"}
        })
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        json_rpc(rid, {
            "tools": [
                {
                    "name": "svm_store",
                    "description": "Store a memory block in SVM (Structured Visual Memory)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "Unique key for the memory block"},
                            "value": {"type": "string", "description": "Content/value of the memory block"},
                            "slot_id": {"type": "string", "description": "Optional slot/group identifier"},
                            "tenant_id": {"type": "string", "description": "Optional tenant ID (default: default)"},
                        },
                        "required": ["key", "value"]
                    }
                },
                {
                    "name": "svm_recall",
                    "description": "Recall memory blocks from SVM by keywords",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "keywords": {"type": "array", "items": {"type": "string"}, "description": "Keywords to search for"},
                            "top_n": {"type": "number", "description": "Maximum results (default: 5)"},
                            "tenant_id": {"type": "string", "description": "Optional tenant ID"},
                            "slot_id": {"type": "string", "description": "Optional slot/group filter"}
                        },
                        "required": ["keywords"]
                    }
                },
                {
                    "name": "svm_forget",
                    "description": "Delete a memory block by key",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "Key of the block to delete"},
                            "tenant_id": {"type": "string", "description": "Optional tenant ID"}
                        },
                        "required": ["key"]
                    }
                },
                {
                    "name": "svm_list",
                    "description": "List all memory blocks",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "tenant_id": {"type": "string", "description": "Optional tenant ID"},
                            "slot_id": {"type": "string", "description": "Optional slot/group filter"}
                        }
                    }
                },
                {
                    "name": "svm_stats",
                    "description": "Get SVM memory statistics",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "tenant_id": {"type": "string", "description": "Optional tenant ID"}
                        }
                    }
                },
                {
                    "name": "svm_audit",
                    "description": "Query SVM audit log",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "description": "Filter by action (store/recall/forget/config_change)"},
                            "limit": {"type": "number", "description": "Max records (default: 20)"}
                        }
                    }
                },
            ]
        })
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        result = handle_tool_call(name, args)
        json_rpc(rid, {"content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}]})
    else:
        json_rpc(rid, error={"code": -32601, "message": f"Method not found: {method}"})


def handle_tool_call(name, args):
    if name == "svm_store":
        cmd = ["store", "--key", args["key"], "--value", args["value"]]
        if args.get("slot_id"):
            cmd += ["--slot", args["slot_id"]]
        if args.get("tenant_id"):
            cmd += ["--tenant", args["tenant_id"]]
        return _svm(cmd)
    elif name == "svm_recall":
        cmd = ["recall"]
        for kw in args.get("keywords", []):
            cmd += ["--keyword", kw]
        if args.get("top_n"):
            cmd += ["--top-n", str(args["top_n"])]
        if args.get("tenant_id"):
            cmd += ["--tenant", args["tenant_id"]]
        if args.get("slot_id"):
            cmd += ["--slot", args["slot_id"]]
        return _svm(cmd)
    elif name == "svm_forget":
        cmd = ["forget", "--key", args["key"]]
        if args.get("tenant_id"):
            cmd += ["--tenant", args["tenant_id"]]
        return _svm(cmd)
    elif name == "svm_list":
        cmd = ["list"]
        if args.get("tenant_id"):
            cmd += ["--tenant", args["tenant_id"]]
        if args.get("slot_id"):
            cmd += ["--slot", args["slot_id"]]
        return _svm(cmd)
    elif name == "svm_stats":
        cmd = ["stats"]
        if args.get("tenant_id"):
            cmd += ["--tenant", args["tenant_id"]]
        return _svm(cmd)
    elif name == "svm_audit":
        cmd = ["audit"]
        if args.get("action"):
            cmd += ["--action", args["action"]]
        if args.get("limit"):
            cmd += ["--limit", str(args["limit"])]
        return _svm(cmd)
    return {"ok": False, "error": f"Unknown tool: {name}"}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            handle_request(msg)
        except json.JSONDecodeError:
            pass
        except Exception as e:
            json_rpc(None, error={"code": -32603, "message": str(e)})


if __name__ == "__main__":
    main()
