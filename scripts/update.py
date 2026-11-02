#!/usr/bin/env python3
"""
抓取多个节点源 -> 合并 -> 去重 -> TCP 测活 -> 生成 Shadowrocket 订阅。

输出:
    docs/sub.txt    base64 编码的订阅内容（小火箭填这个地址）
    docs/nodes.txt  明文节点列表（方便自己查看）

用法:
    python3 scripts/update.py            # 完整流程（含测活）
    SKIP_CHECK=1 python3 scripts/update.py   # 跳过测活，只做合并去重
"""

import base64
import collections
import json
import os
import re
import socket
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, unquote, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")

CHECK_TIMEOUT = float(os.environ.get("CHECK_TIMEOUT", "3"))
CHECK_WORKERS = int(os.environ.get("CHECK_WORKERS", "64"))
SKIP_CHECK = os.environ.get("SKIP_CHECK", "") == "1"
MAX_NODES = int(os.environ.get("MAX_NODES", "600"))


def log(*a):
    print(*a, flush=True)


def b64fix(s):
    s = s.replace("-", "+").replace("_", "/")
    return s + "=" * (-len(s) % 4)


def fetch(url, timeout=20):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; sub-updater/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def decode_maybe_base64(text):
    """订阅内容可能是明文，也可能是整段 base64。"""
    t = text.strip()
    if "://" in t:
        return t
    try:
        dec = base64.b64decode(b64fix(t), validate=False).decode("utf-8", "ignore")
        if "://" in dec:
            return dec
    except Exception:
        pass
    return text


def parse_node(line):
    """解析单行节点链接，返回 {raw, proto, host, port, key} 或 None。"""
    line = line.strip()
    if "://" not in line:
        return None
    scheme = line.split("://", 1)[0].lower()
    body = line.split("://", 1)[1]
    try:
        if scheme == "ss":
            b = body.split("#", 1)[0].split("?", 1)[0]
            if "@" in b:
                userinfo, hp = b.rsplit("@", 1)
                dec = base64.b64decode(b64fix(userinfo)).decode("utf-8", "ignore")
                pwd = dec.split(":", 1)[-1]
                m = re.match(r"(.+):(\d+)$", hp)
                if not m:
                    return None
                host, port = m.group(1), int(m.group(2))
            else:
                dec = base64.b64decode(b64fix(b)).decode("utf-8", "ignore")
                m = re.match(r"(.+?):(.+)@(.+):(\d+)$", dec)
                if not m:
                    return None
                pwd, host, port = m.group(2), m.group(3), int(m.group(4))
            return dict(raw=line, proto="ss", host=host, port=port,
                        key=f"ss|{host}|{port}|{pwd}")

        if scheme in ("trojan", "vless", "vmess"):
            if scheme == "vmess":
                info = json.loads(base64.b64decode(b64fix(body)).decode("utf-8", "ignore"))
                host, port, pwd = info["add"], int(info["port"]), info["id"]
            else:
                u = urlparse(scheme + "://" + body.split("#", 1)[0])
                host, port = u.hostname, int(u.port or 443)
                pwd = unquote(u.username or "")
            if not host or not port:
                return None
            return dict(raw=line, proto=scheme, host=host, port=port,
                        key=f"{scheme}|{host}|{port}|{pwd}")
    except Exception:
        return None
    return None


def tcp_alive(node):
    host, port = node["host"], node["port"]
    try:
        with socket.create_connection((host, port), timeout=CHECK_TIMEOUT):
            return True
    except Exception:
        return False


def collect_sources():
    """读取 sources.txt：每行一个订阅 URL 或本地文件路径，# 开头为注释。"""
    path = os.path.join(ROOT, "sources.txt")
    items = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if line and not line.startswith("#"):
                items.append(line)

    chunks = []
    for item in items:
        try:
            if item.startswith("http://") or item.startswith("https://"):
                log(f"  抓取 {item}")
                chunks.append(decode_maybe_base64(fetch(item)))
            else:
                p = item if os.path.isabs(item) else os.path.join(ROOT, item)
                if os.path.exists(p):
                    log(f"  读取本地 {item}")
                    chunks.append(decode_maybe_base64(open(p, encoding="utf-8", errors="ignore").read()))
                else:
                    log(f"  [跳过] 找不到 {item}")
        except Exception as e:
            log(f"  [失败] {item}: {e}")
    return chunks


def main():
    log("== 收集节点源 ==")
    chunks = collect_sources()
    if not chunks:
        log("没有任何可用源，退出")
        return 1

    raw_lines = []
    for c in chunks:
        raw_lines.extend([l.strip() for l in c.splitlines() if l.strip()])

    log(f"== 解析 {len(raw_lines)} 行 ==")
    nodes, bad = [], 0
    for line in raw_lines:
        n = parse_node(line)
        if n:
            nodes.append(n)
        else:
            bad += 1
    log(f"   有效 {len(nodes)}，无法解析 {bad}")

    # 去重（保留首次出现）
    seen, uniq = set(), []
    for n in nodes:
        if n["key"] not in seen:
            seen.add(n["key"])
            uniq.append(n)
    log(f"   去重后 {len(uniq)}（剔除重复 {len(nodes) - len(uniq)}）")

    if not SKIP_CHECK:
        log(f"== 测活（超时 {CHECK_TIMEOUT}s，并发 {CHECK_WORKERS}）==")
        with ThreadPoolExecutor(max_workers=CHECK_WORKERS) as ex:
            flags = list(ex.map(tcp_alive, uniq))
        alive = [n for n, ok in zip(uniq, flags) if ok]
        log(f"   存活 {len(alive)} / {len(uniq)}")
        if len(alive) >= 20:
            uniq = alive
        else:
            log("   存活过少，保留全部以免订阅为空")
    else:
        log("== 跳过测活 ==")

    # 按协议+地区排序，名称更整齐
    uniq.sort(key=lambda n: (n["proto"], n["host"]))
    if len(uniq) > MAX_NODES:
        uniq = uniq[:MAX_NODES]

    lines = [n["raw"] for n in uniq]
    os.makedirs(DOCS, exist_ok=True)

    plain = "\n".join(lines) + "\n"
    open(os.path.join(DOCS, "nodes.txt"), "w", encoding="utf-8").write(plain)
    open(os.path.join(DOCS, "sub.txt"), "w", encoding="utf-8").write(
        base64.b64encode(plain.encode()).decode()
    )

    stat = collections.Counter(n["proto"] for n in uniq)
    log(f"== 完成：写入 {len(uniq)} 个节点 ==")
    log(f"   协议分布 {dict(stat)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
