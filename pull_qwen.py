import requests, json, sys, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

model_name = "qwen2.5:0.5b"
print(f"正在拉取 {model_name}（约 300MB，阿里千问，中文效果最佳）...")
print()

start = time.time()
resp = requests.post(
    "http://127.0.0.1:11434/api/pull",
    json={"name": model_name, "stream": True},
    stream=True,
    timeout=600
)
resp.raise_for_status()

for line in resp.iter_lines(decode_unicode=True):
    if line:
        try:
            data = json.loads(line)
            status = data.get("status", "")
            if "downloading" in status:
                total = data.get("total", 0)
                completed = data.get("completed", 0)
                if total:
                    pct = completed / total * 100
                    bar = "#" * int(pct / 5) + "." * (20 - int(pct / 5))
                    print(f"\r  [{bar}] {pct:.0f}%", end="")
                else:
                    print(f"\r  {status}", end="")
            elif status == "success":
                elapsed = time.time() - start
                print(f"\n  完成！耗时 {elapsed:.0f}s")
                break
            else:
                print(f"\r  {status}")
        except:
            pass
