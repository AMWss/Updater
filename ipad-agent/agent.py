#!/usr/bin/env python3
"""Sheng iPad Agent v1.1 — GitHub mailbox, local approval, no root."""
import base64
import datetime as dt
import getpass
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

VERSION = "1.1.0"
APP = pathlib.Path.home() / ".config" / "sheng-ipad-agent"
CONF = APP / "config.json"
SEEN = APP / "handled.json"
LOGS = APP / "results"
WORK = pathlib.Path.home() / "Documents" / "ShengAgentWork"
API = "https://api.github.com"
ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")
PACKAGE_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,60}$")


def as_mobile():
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise RuntimeError("请在 NewTerm 中以 mobile 用户运行，不要用 root 或 sudo")


def write_json(path, obj):
    APP.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp." + uuid.uuid4().hex)
    with open(temp, "x", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def read_json(path, fallback=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return fallback


def cfg_load():
    c = read_json(CONF)
    if not c or not all(c.get(k) for k in ("owner", "repo", "branch", "token")):
        raise RuntimeError("尚未配置 GitHub。运行 sheng-agent setup")
    return c


def api(c, method, endpoint, payload=None, absent=False):
    headers = {
        "Authorization": "Bearer " + c["token"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Sheng-iPad-Agent/" + VERSION,
    }
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + endpoint, headers=headers, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read(200000)
        return json.loads(data.decode("utf-8")) if data else {}
    except urllib.error.HTTPError as ex:
        if absent and ex.code == 404:
            return None
        raise RuntimeError("GitHub 请求失败：HTTP %d" % ex.code)
    except urllib.error.URLError as ex:
        raise RuntimeError("网络错误：%s" % ex.reason)


def repo_endpoint(c, path):
    parts = [c["owner"], c["repo"]]
    return "/repos/" + "/".join(urllib.parse.quote(x, safe="") for x in parts) + "/contents/" + "/".join(urllib.parse.quote(x, safe="") for x in path.split("/"))


def get_file(c, path):
    e = repo_endpoint(c, path) + "?ref=" + urllib.parse.quote(c["branch"], safe="")
    obj = api(c, "GET", e, absent=True)
    if obj is None:
        return None, None
    if obj.get("type") != "file" or obj.get("encoding") != "base64":
        raise RuntimeError("GitHub 文件格式不支持")
    data = base64.b64decode(obj["content"])
    if len(data) > 60000:
        raise RuntimeError("远程任务文件太大")
    return data.decode("utf-8"), obj["sha"]


def put_file(c, path, content):
    _, sha = get_file(c, path)
    obj = {
        "branch": c["branch"],
        "message": "sheng-agent: " + path,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        obj["sha"] = sha
    return api(c, "PUT", repo_endpoint(c, path), obj)


def setup():
    as_mobile()
    print("Sheng Agent — 配置 GitHub 私有任务仓库")
    print("请准备仅限单个私有仓库、Contents 读写权限的 Fine-grained Token。")
    prior = read_json(CONF, {})
    repo = input("私有仓库 owner/repo: ").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("请输入 owner/repo")
    branch = input("分支（直接回车为 main）: ").strip() or "main"
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", branch) or ".." in branch:
        raise ValueError("分支名称不合法")
    token = getpass.getpass("GitHub Token（不回显）: ").strip()
    if not token:
        raise ValueError("必须提供 Token")
    owner, name = repo.split("/")
    c = {"owner": owner, "repo": name, "branch": branch, "token": token, "allow_shell": False}
    info = api(c, "GET", "/repos/" + owner + "/" + name)
    if not info.get("private"):
        raise ValueError("任务仓库必须为 Private；不要用公共仓库存放执行结果")
    write_json(CONF, c)
    print("配置完成。可以运行 sheng-agent publish-demo，再运行 sheng-agent once")


def doctor():
    print("Sheng iPad Agent", VERSION)
    print("Python:", sys.version.split()[0])
    print("uid:", os.geteuid() if hasattr(os, "geteuid") else "?")
    print("HOME:", pathlib.Path.home())
    print("Rootless /var/jb:", pathlib.Path("/var/jb").exists())
    for name in ("curl", "python3", "ssh", "dpkg", "apt"):
        print(name + ":", shutil.which(name) or "未找到")
    print("任务仓库配置:", "已有" if CONF.exists() else "尚未配置")


def stamp(v):
    d = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("时间必须带时区")
    return d


def demo_task():
    now = dt.datetime.now(dt.timezone.utc)
    fmt = lambda t: t.isoformat(timespec="seconds").replace("+00:00", "Z")
    return {"id": "demo-" + uuid.uuid4().hex[:10],
            "title": "查看 iPad 系统信息", "action": "system_report", "params": {},
            "created_at": fmt(now), "expires_at": fmt(now + dt.timedelta(hours=1))}


def verify(task):
    if not isinstance(task, dict) or not ID_RE.fullmatch(str(task.get("id", ""))):
        raise ValueError("任务 ID 格式错误")
    if not isinstance(task.get("params"), dict) or not isinstance(task.get("title"), str):
        raise ValueError("任务缺少标题或 params")
    if len(task["title"]) > 120:
        raise ValueError("标题过长")
    actions = {
        "system_report": set(),
        "disk_usage": set(),
        "package_status": {"package"},
        "list_workspace": set(),
        "write_text": {"name", "text"},
        "shell": {"command"},
    }
    action = task.get("action")
    if action not in actions or set(task["params"]) != actions[action]:
        raise ValueError("不认识的操作或参数")
    created = stamp(task["created_at"])
    expires = stamp(task["expires_at"])
    now = dt.datetime.now(dt.timezone.utc)
    if created > now + dt.timedelta(minutes=5) or expires < now or expires <= created or expires - created > dt.timedelta(hours=24):
        raise ValueError("任务已过期或时间无效")
    p = task["params"]
    if action == "package_status" and (not isinstance(p["package"], str) or not PACKAGE_RE.fullmatch(p["package"])):
        raise ValueError("软件包名称无效")
    if action == "write_text":
        if not isinstance(p["name"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,60}\\.(txt|md)", p["name"]):
            raise ValueError("只能在工作目录创建简单 txt/md 文件")
        if not isinstance(p["text"], str) or len(p["text"].encode("utf-8")) > 10000:
            raise ValueError("文本不得超过 10KB")
    if action == "shell" and (not isinstance(p["command"], str) or len(p["command"]) > 300):
        raise ValueError("Shell 指令过长")
    return action


def run_cmd(args, shell=False):
    try:
        res = subprocess.run(args, shell=shell, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20, cwd=str(pathlib.Path.home()))
        return {"returncode": res.returncode, "output": res.stdout[:10000]}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "output": "超时 20 秒，任务被终止"}


def execute(action, params):
    if action == "system_report":
        return {"returncode": 0, "output": "uid=%s\npython=%s\nsystem=%s\nrootless=%s" % (os.geteuid(), sys.version.split()[0], sys.platform, pathlib.Path("/var/jb").exists())}
    if action == "disk_usage":
        return run_cmd(["df", "-h"])
    if action == "package_status":
        return run_cmd(["dpkg", "-s", params["package"]])
    if action == "list_workspace":
        WORK.mkdir(parents=True, exist_ok=True)
        return {"returncode": 0, "output": "\n".join(sorted(p.name for p in WORK.iterdir()))[:10000]}
    if action == "write_text":
        WORK.mkdir(parents=True, exist_ok=True)
        dest = WORK / params["name"]
        with open(dest, "x", encoding="utf-8") as out:
            out.write(params["text"])
        return {"returncode": 0, "output": "Created " + str(dest)}
    if action == "shell":
        return run_cmd(params["command"], shell=True)
    raise ValueError("未知操作")


def run_task(task, c=None):
    as_mobile()
    action = verify(task)
    seen = read_json(SEEN, [])
    if task["id"] in seen:
        print("任务已处理过，拒绝重放:", task["id"])
        return
    print("\n--- 待授权任务 ---")
    print(json.dumps(task, ensure_ascii=False, indent=2))
    if action == "shell" and not (c or read_json(CONF, {})).get("allow_shell"):
        print("Shell 默认关闭，拒绝执行。")
        outcome = {"status": "blocked", "output": "shell disabled"}
    else:
        yes = "YES " + task["id"]
        approved = input("仅当你理解任务时输入 " + yes + " : ").strip() == yes
        if approved and action == "shell":
            approved = input("Shell 可访问用户文件，再输入 ALLOW SHELL 确认: ").strip() == "ALLOW SHELL"
        if not approved:
            outcome = {"status": "rejected", "output": "用户未批准"}
        else:
            try:
                result = execute(action, task["params"])
                outcome = {"status": "done", **result}
            except Exception as ex:
                outcome = {"status": "error", "output": str(ex)}
    seen.append(task["id"])
    write_json(SEEN, seen[-1000:])
    record = {"id": task["id"], "action": action, **outcome}
    write_json(LOGS / (task["id"] + ".json"), record)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    if c:
        try:
            put_file(c, "results/" + task["id"] + ".json", json.dumps(record, ensure_ascii=False, indent=2))
            print("✅ 结果已回传 GitHub")
        except Exception as ex:
            print("结果已保存在本机，但回传失败：", ex)
    return record


def once():
    c = cfg_load()
    content, _ = get_file(c, "tasks/pending.json")
    if content is None:
        print("还没有待处理任务：tasks/pending.json")
        return
    task = json.loads(content)
    run_task(task, c)


def toggle_shell(allow):
    as_mobile()
    c = cfg_load()
    c["allow_shell"] = allow
    write_json(CONF, c)
    print("Shell 已" + ("启用，但每条任务仍需双重批准" if allow else "关闭"))


def main():
    os.umask(0o077)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "doctor"
    if cmd == "doctor":
        doctor()
    elif cmd == "setup":
        setup()
    elif cmd == "local-demo":
        run_task(demo_task())
    elif cmd == "publish-demo":
        c = cfg_load()
        put_file(c, "tasks/pending.json", json.dumps(demo_task(), ensure_ascii=False, indent=2))
        print("测试任务已发布；运行 sheng-agent once")
    elif cmd == "once":
        once()
    elif cmd == "watch":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        interval = max(10, min(3600, interval))
        print("每 %d 秒读取任务；Ctrl+C 退出" % interval)
        while True:
            try:
                once()
            except Exception as ex:
                print("轮询出错：", ex)
            time.sleep(interval)
    elif cmd == "enable-shell":
        toggle_shell(True)
    elif cmd == "disable-shell":
        toggle_shell(False)
    else:
        print("命令：doctor | setup | local-demo | publish-demo | once | watch [seconds] | enable-shell | disable-shell")
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, KeyboardInterrupt) as ex:
        print("错误：", ex, file=sys.stderr)
        raise SystemExit(1)
