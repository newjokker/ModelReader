import os
import json
import requests

API_KEY = "sk-api-Vdtg007Z5yclxtrz_67WZ7HPuJ4R_yHEZF5C9qlxVXMFCxSt9sGZ3E4RC7Ho4mJNOPm4sMVUUEHpemT73QVdoQmzv1lBDhp_9DDCC57um366-RtaVUvB7jE"

url = "https://api.minimax.io/v1/get_voice"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

payload = {
    "voice_type": "system"
}

resp = requests.post(url, headers=headers, json=payload, timeout=30)
resp.raise_for_status()

data = resp.json()

if data.get("base_resp", {}).get("status_code") != 0:
    raise RuntimeError(data)

voices = data.get("system_voice", [])

print(f"系统音色数量: {len(voices)}\n")

for v in voices:
    print(f"voice_id: {v.get('voice_id')}")
    print(f"voice_name: {v.get('voice_name')}")
    desc = v.get("description") or []
    if desc:
        print(f"description: {'; '.join(desc)}")
    print("-" * 60)

# 保存为 json
with open("minimax_system_voices.json", "w", encoding="utf-8") as f:
    json.dump(voices, f, ensure_ascii=False, indent=2)

print("\n已保存到 minimax_system_voices.json")