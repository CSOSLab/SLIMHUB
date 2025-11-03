#!/usr/bin/env python3
# db_ingest_today.py
# - DATA_ROOT 하위의 debugstr/{YYYY-MM-DD}.txt(JSON lines)에서
#   오늘 추가분만 읽어 event_adl에 적재
# - 파일별 라인 오프셋 추적으로 중복 삽입 방지

import os
import json
import pymysql
from datetime import datetime
from glob import glob
from typing import List, Tuple

# ===================== 전역 설정 =====================

DATA_ROOT   = "/home/rtlab/SLIMHUB/data"                  # ✅ 최상위 데이터 경로
SUB_FOLDERS = ["LIVING", "KITCHEN", "ENTRY", "TOILET", "BEDROOM"]
PATTERNS    = ["debugstr"]                                 # ← debugstr만 처리
TODAY       = datetime.now().strftime("%Y-%m-%d")
TRACKER_DIR = "log_dir"                                    # 오프셋 저장 경로

def env_or_default(key, default):
    return os.getenv(key, default)

DB_CONF = {
    "host": env_or_default("ADL_DB_HOST", "localhost"),
    "port": int(env_or_default("ADL_DB_PORT", "3306")),
    "user": env_or_default("ADL_DB_USER", "givemeadl"),
    "password": env_or_default("ADL_DB_PASS", "rtlab!123"),
    "database": env_or_default("ADL_DB_NAME", "adl_event"),
    "charset": "utf8mb4",
}
TABLE_NAME = env_or_default("ADL_TABLE", "event_adl")      # event_adl 스키마에 적재

# ===================== 유틸 =====================

def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

def extract_mac(path: str) -> str:
    parts = path.split(os.sep)
    if "DE&N" in parts:
        i = parts.index("DE&N")
        if i + 1 < len(parts): return parts[i + 1]
    return "unknown"

def tracker_key(path: str) -> str:
    return f"{extract_mac(path)}_{os.path.basename(path)}.line"

def read_last_line_index(path: str) -> int:
    ensure_dir(TRACKER_DIR)
    p = os.path.join(TRACKER_DIR, tracker_key(path))
    if not os.path.exists(p): return 0
    try:
        with open(p, "r", encoding="utf-8") as f:
            s = f.read().strip()
            return int(s) if s else 0
    except Exception:
        return 0

def write_last_line_index(path: str, idx: int):
    ensure_dir(TRACKER_DIR)
    p = os.path.join(TRACKER_DIR, tracker_key(path))
    with open(p, "w", encoding="utf-8") as f:
        f.write(str(idx))

def parse_ts(s: str):
    if not s: return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

# ===================== 파일 검색 & 파싱 =====================

def discover_files_today() -> List[Tuple[str, str]]:
    out = []
    for sub in SUB_FOLDERS:
        root = os.path.join(DATA_ROOT, sub)
        for patt in PATTERNS:
            pattern = os.path.join(root, "**", "DE&N", "*", "inference", patt, f"{TODAY}.txt")
            #pattern = os.path.join(root, "**", "DE&N", "*", "inference", patt, "2025-10-22.txt")
            for fp in glob(pattern, recursive=True):
                out.append((fp, patt))
    # 중복 제거
    seen, uniq = set(), []
    for fp, patt in out:
        if fp not in seen:
            uniq.append((fp, patt)); seen.add(fp)
    return uniq

def parse_debugstr_line(line: str):
    s = (line or "").strip()
    if not s: return None
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None
    device = obj.get("device")
    ts     = parse_ts(obj.get("timestamp"))
    seq    = (obj.get("sequence") or "").strip() or None
    adl    = obj.get("ADL")
    truth  = obj.get("truth")
    if not device or not ts: return None
    return [None, device, ts, seq, adl, truth]  # house_mac=None

# ===================== DB =====================

def insert_rows(rows: List[list]) -> int:
    if not rows: return 0
    conn = pymysql.connect(**DB_CONF)
    try:
        with conn.cursor() as cur:
            sql = f"""
                INSERT INTO {TABLE_NAME}
                  (house_mac, location, created_time, event_sequence, adl, truth_value)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)

# ===================== 메인 =====================

def process_file(fp: str) -> int:
    # JSONL은 헤더 없음 → 오프셋은 "라인 개수" 그대로 사용
    with open(fp, "r", encoding="utf-8") as f:
        lines = f.readlines()

    last_idx = read_last_line_index(fp)
    lines_new = lines[last_idx:] if last_idx < len(lines) else []
    rows = []
    for ln in lines_new:
        r = parse_debugstr_line(ln)
        if r: rows.append(r)

    n = insert_rows(rows)
    if n:
        write_last_line_index(fp, len(lines))
    return n

def main():
    files = discover_files_today()
    print(f"[INGEST] debugstr files={len(files)} date={TODAY} root={DATA_ROOT}")
    total = 0
    for fp, _ in files:
        n = process_file(fp)
        print(f"  - {fp} → inserted={n}")
        total += n
    print(f"[DONE] total_inserted={total}")

if __name__ == "__main__":
    main()
