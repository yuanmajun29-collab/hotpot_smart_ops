#!/usr/bin/env python3
"""Fix camera password in cameras.json"""
import json

CAMERAS_FILE = "/opt/hotpot-smart-ops/edge/edge-ui/conf/cameras.json"

with open(CAMERAS_FILE, 'r') as f:
    data = json.load(f)

for cam in data.get("cameras", []):
    if cam.get("credentials") and cam["credentials"].get("password") == "******":
        cam["credentials"]["password"] = "hy898989"
        print(f"Fixed password for camera: {cam.get('id')}")

with open(CAMERAS_FILE, 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Done!")
