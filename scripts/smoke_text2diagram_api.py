import json
import time
import urllib.request

BASE = "http://127.0.0.1:8420"
PAYLOAD = {
    "source_text": "Encoder extracts visual tokens, cross-attention fuses prompt features, decoder predicts segmentation mask.",
    "caption": "Method pipeline overview",
    "diagram_type": "methodology",
    "iterations": 1,
}

req = urllib.request.Request(
    BASE + "/api/text-to-diagram/jobs",
    data=json.dumps(PAYLOAD).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    job_id = json.loads(resp.read().decode())["job_id"]

print("JOB_ID", job_id)

start = time.time()
while True:
    with urllib.request.urlopen(BASE + f"/api/text-to-diagram/jobs/{job_id}", timeout=30) as resp:
        data = json.loads(resp.read().decode())

    print(
        "STATUS",
        data["status"],
        "events",
        len(data.get("events", [])),
        "iters",
        len(data.get("iterations", [])),
        "final",
        bool(data.get("final_image_url")),
    )

    if data["status"] in ("completed", "failed"):
        print("FINAL_STATUS", data["status"])
        print("FINAL_IMAGE", data.get("final_image_url"))
        print("ERROR", data.get("error"))
        break

    if time.time() - start > 900:
        print("TIMEOUT")
        break

    time.sleep(2)
