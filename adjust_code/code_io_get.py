#!/usr/bin/env python3
# rawdata_pick_today_ingest.py
# - DATA_ROOT 하위 rawdata/{YYYY-MM-DD}.txt(CSV)에서
#   GridEye == 1 인 행만 골라 time, GridEye, Direction → event_raw_pick 적재
# - 헤더 1줄 + 데이터 N줄 구조 → "데이터 라인" 기준 오프셋 저장(중복 방지)

import os
import csv
import pymysql
from datetime import datetime
from glob import glob
from typing import List, Tuple

# ===================== 전역 설정 =====================

DATA_ROOT   = "/home/rtlab/SLIMHUB/data"
SUB_FOLDERS = ["LIVING", "KITCHEN", "ENTRY", "TOILET", "BEDROOM"]
TODAY       = datetime.now().strftime("%Y-%m-%d")
TRACKER_DIR = "log_dir_rawpick"

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

TABLE_NAME = "in_out"  # 분리 테이블에 적재

# ===================== 유틸 =====================

def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

def extract_mac(path: str) -> str:
    parts = path.split(os.sep)
    if "DE&N" in parts:
        i = parts.index("DE&N")
        if i + 1 < len(parts): return parts[i + 1]
    return "unknown"

def extract_room(path: str) -> str:
    parts = path.split(os.sep)
    try:
        idx = parts.index(os.path.basename(DATA_ROOT)) + 1
        return parts[idx]
    except Exception:
        return "unknown"

def location_from_path(path: str) -> str:
    # 방/맥 중 택일 가능: return extract_mac(path)  혹은 return extract_room(path)
    return f"{extract_room(path)}:{extract_mac(path)}"

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

def discover_rawdata_files_today() -> List[str]:
    out = []
    for sub in SUB_FOLDERS:
        pattern = os.path.join(DATA_ROOT, sub, "**", "inference", "rawdata", f"{TODAY}.txt")
        #pattern = os.path.join(DATA_ROOT, sub, "**", "inference", "rawdata", "2025-10-22.txt")
        out.extend(glob(pattern, recursive=True))
    # 중복 제거
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            uniq.append(p); seen.add(p)
    return uniq

def slice_csv_lines(path: str) -> Tuple[List[str], int]:
    """
    파일 전체를 읽어 헤더/데이터 분리.
    오프셋은 '데이터 라인 수(헤더 제외)' 기준으로 관리.
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        lines = f.readlines()
    if not lines: return [], 0
    header, data_lines = lines[0], lines[1:]
    last_idx = read_last_line_index(path)
    new_data = data_lines[last_idx:] if last_idx < len(data_lines) else []
    # DictReader를 위해 헤더를 다시 앞에 붙여 반환
    return [header] + new_data, len(data_lines)

def parse_and_filter_rows(path: str) -> Tuple[List[tuple], int]:
    """
    반환: [(location, created_time, grid_eye, direction), ...], total_data_lines
    - CSV 헤더: time,GridEye,Direction,...
    - GridEye == '1' 인 행만 추출
    """
    slice_lines, total_data = slice_csv_lines(path)
    if not slice_lines: return [], total_data

    loc = location_from_path(path)
    out = []
    reader = csv.DictReader(slice_lines)
    for row in reader:
        #print(row)
        if row is None: continue
        if (row.get("GridEye") or "").strip() != "1":  # 필터
            continue
        t  = (row.get("time") or "").strip()
        d  = (row.get("Direction") or "").strip()
        ts = parse_ts(t)
        if not (t and d and ts):
            continue
        out.append((0, loc, t, d))
    return out, total_data

# ===================== DB =====================

def insert_rows(rows: List[tuple]) -> int:
    if not rows: return 0
    conn = pymysql.connect(**DB_CONF)

    try:
        with conn.cursor() as cur:
            sql = f"""
                INSERT INTO {TABLE_NAME}
                  (house_mac, location, created_time, direction)
                VALUES (%s, %s, %s, %s)
            """
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)

# ===================== 메인 =====================

def main():
    files = discover_rawdata_files_today()
    print(f"[PICK] rawdata files={len(files)} date={TODAY} root={DATA_ROOT}")
    total = 0
    for fp in files:
        rows, end_idx = parse_and_filter_rows(fp)
        n = insert_rows(rows)
        if n:
            write_last_line_index(fp, end_idx)  # 성공 시에만 오프셋 갱신
        print(f"  - {fp} → picked={len(rows)} inserted={n} offset={end_idx}")
        total += n
    print(f"[DONE] total_inserted={total}")

if __name__ == "__main__":
    main()
