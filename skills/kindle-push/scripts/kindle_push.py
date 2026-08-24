#!/usr/bin/env python3
import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def gog_env(cfg):
    env = dict(os.environ)
    env["GOG_KEYRING_PASSWORD"] = cfg.get("keyring_password", "") or ""
    env["GOG_ACCOUNT"] = cfg.get("account", "")
    return env


def search_local(cfg, query):
    matches = []
    for d in cfg.get("local_dirs", []):
        root = os.path.expanduser(d)
        if not os.path.isdir(root):
            continue
        for base in (root,):
            for pattern in ("**/*",):
                for path in glob.glob(os.path.join(base, pattern), recursive=True):
                    if not os.path.isfile(path):
                        continue
                    name = os.path.basename(path)
                    if query.lower() in name.lower() or query.lower() in os.path.splitext(name)[0].lower():
                        matches.append({"source": "local", "path": path, "name": name})
    return matches


def search_drive(cfg, query):
    env = gog_env(cfg)
    cmd = [
        "gog", "drive", "search", query,
        "--max", "10", "--json", "--no-input",
        "--account", cfg.get("account", ""),
    ]
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return [], "gog drive search 超时"
    if proc.returncode != 0:
        return [], proc.stderr.strip()
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [], "gog drive search 输出解析失败"
    files = data.get("files", data if isinstance(data, list) else [])
    result = []
    for f in files:
        fid = f.get("id")
        name = f.get("name")
        if fid and name:
            result.append({"source": "drive", "id": fid, "name": name})
    return result, None


def download_drive(cfg, file_id, name):
    env = gog_env(cfg)
    tmp = tempfile.mkdtemp(prefix="kindle_")
    out = os.path.join(tmp, name)
    cmd = [
        "gog", "drive", "download", file_id,
        "--out", out, "--no-input",
        "--account", cfg.get("account", ""),
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or not os.path.exists(out):
        return None, proc.stderr.strip()
    return out, None


def check_file(cfg, path):
    ext = os.path.splitext(path)[1].lower()
    allowed = [e.lower() for e in cfg.get("allowed_ext", [".epub", ".pdf"])]
    if ext not in allowed:
        return False, f"不支持格式 {ext}，仅支持 {allowed}（mobi 请先转 epub）"
    size_mb = os.path.getsize(path) / (1024 * 1024)
    limit = cfg.get("max_size_mb", 25)
    if size_mb > limit:
        return False, f"文件 {size_mb:.1f}MB 超过上限 {limit}MB"
    return True, None


def send_to_kindle(cfg, file_path):
    env = gog_env(cfg)
    cmd = [
        "gog", "gmail", "send",
        "--to", cfg["kindle_email"],
        "--subject", "Convert",
        "--body", "Sent via kindle-push",
        "--attach", file_path,
        "--no-input", "--force",
        "--account", cfg.get("account", ""),
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        return False, proc.stderr.strip()
    return True, None


def choose(results):
    if not results:
        return None
    if len(results) == 1:
        return results[0]
    print("找到多个文件：")
    for i, r in enumerate(results, 1):
        tag = "本地" if r["source"] == "local" else "Drive"
        print(f"  {i}. [{tag}] {r['name']}")
    while True:
        try:
            sel = input("选择序号 (回车=取消): ").strip()
            if not sel:
                return None
            return results[int(sel) - 1]
        except (ValueError, IndexError):
            print("无效序号")


def main():
    parser = argparse.ArgumentParser(description="推送电子书到 Kindle")
    parser.add_argument("query", help="书名或本地路径")
    parser.add_argument("--no-drive", action="store_true", help="跳过 Drive 搜索")
    args = parser.parse_args()

    cfg = load_config()
    if not cfg.get("keyring_password"):
        print("错误：config.json 未设置 keyring_password", file=sys.stderr)
        sys.exit(1)

    query = args.query

    direct = None
    if os.path.isfile(query):
        direct = {"source": "local", "path": query, "name": os.path.basename(query)}

    local_matches = [] if direct else search_local(cfg, query)
    drive_matches, drive_err = ([], None) if args.no_drive else search_drive(cfg, query)
    if drive_err and not local_matches:
        print(f"警告：Drive 搜索失败：{drive_err}", file=sys.stderr)

    results = ([direct] if direct else []) + local_matches + drive_matches
    if not results:
        print(f"未找到匹配 '{query}' 的文件")
        sys.exit(1)

    chosen = choose(results)
    if not chosen:
        print("已取消")
        sys.exit(0)

    file_path = None
    if chosen["source"] == "local":
        file_path = chosen["path"]
    else:
        file_path, dl_err = download_drive(cfg, chosen["id"], chosen["name"])
        if not file_path:
            print(f"Drive 下载失败：{dl_err}", file=sys.stderr)
            sys.exit(1)

    ok, err = check_file(cfg, file_path)
    if not ok:
        print(f"校验失败：{err}", file=sys.stderr)
        sys.exit(1)

    ok, err = send_to_kindle(cfg, file_path)
    if ok:
        print(f"成功：{chosen['name']} 已发送至 Kindle {cfg['kindle_email']}，Kindle 连接 Wi-Fi 后自动下载")
    else:
        print(f"发送失败：{err}", file=sys.stderr)
        sys.exit(1)

    if chosen["source"] == "drive":
        os.remove(file_path)
        parent = os.path.dirname(file_path)
        try:
            os.rmdir(parent)
        except OSError:
            pass


if __name__ == "__main__":
    main()
