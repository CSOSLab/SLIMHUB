#!/usr/bin/env python3
# upload_db_simple_auto.py
# - 로컬(adl) → 원격(adl_raw) 증분 업로드
# - 각 스트림별로 로컬에서 컬럼(순서) 자동 추출 → id 제외 후 원격으로 INSERT
# - 로컬/원격 스키마는 동일하다고 가정(테이블마다 다를 수 있음)
# - 심플 버전: 재시도/백오프 없음

import os
import pymysql

# ===== DB 연결 설정 =====
LOCAL = dict(host=os.getenv("LOCAL_DB_HOST","localhost"),
             port=int(os.getenv("LOCAL_DB_PORT","3306")),
             user=os.getenv("LOCAL_DB_USER","givemeadl"),
             password=os.getenv("LOCAL_DB_PASS","rtlab!123"),
             database=os.getenv("LOCAL_DB_NAME","adl_event"),
             charset="utf8mb4", autocommit=True)

REMOTE = dict(host=os.getenv("REMOTE_DB_HOST","155.230.186.52"),
              port=int(os.getenv("REMOTE_DB_PORT","4404")),
              user=os.getenv("REMOTE_DB_USER","Dr_Simon"),
              password=os.getenv("REMOTE_DB_PASS","drsimon1234"),   # ← 환경변수로 주입 권장
              database=os.getenv("REMOTE_DB_NAME","adl_raw"),
              charset="utf8mb4", autocommit=True)

# ===== 스트림 정의 (로컬/원격 테이블 쌍) =====
STREAMS = {
    "ADL":   {"local": "event_adl", "remote": "event_adl",
              "offset": "/home/rtlab/SLIMHUB/code_db_save/log_dir/last_uploaded_id__ADL.txt"},
    "INOUT": {"local": "in_out",    "remote": "in_out",
              "offset": "/home/rtlab/SLIMHUB/code_db_save/log_dir/last_uploaded_id__INOUT.txt"},
}

BATCH_SIZE = int(os.getenv("UPLOAD_BATCH_SIZE", "1000"))

# ===== 유틸 =====
def read_last_id(path: str) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w") as f: f.write("0")
        return 0
    try:
        with open(path, "r") as f:
            return int((f.read().strip() or "0"))
    except:
        return 0

def write_last_id(path: str, v: int):
    with open(path, "w") as f: f.write(str(v))

def get_non_id_columns(conn, table: str):
    """로컬 테이블에서 실제 컬럼 순서를 가져와 id만 제외."""
    with conn.cursor() as cur:
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        cols = [row[0] for row in cur.fetchall()]  # (Field, Type, Null, Key, Default, Extra)
    return [c for c in cols if c.lower() != "id"]

# ===== 메인 처리 =====
def process_stream(name: str):
    cfg = STREAMS[name]
    offset_path = cfg["offset"]
    last_id = read_last_id(offset_path)

    with pymysql.connect(**LOCAL) as lc, lc.cursor() as lcur:
        # 각 스트림(테이블)별로 로컬에서 컬럼 자동 조회
        cols_no_id = get_non_id_columns(lc, cfg["local"])
        if not cols_no_id:
            print(f"[{name}] no columns (excluding id); skip")
            return

        col_list = ", ".join(f"`{c}`" for c in cols_no_id)
        sel_sql = f"SELECT id, {col_list} FROM `{cfg['local']}` WHERE id > %s ORDER BY id ASC LIMIT %s"
        lcur.execute(sel_sql, (last_id, BATCH_SIZE))
        rows = lcur.fetchall()

    if not rows:
        print(f"[{name}] no new rows (last_id={last_id})")
        return

    placeholders = ", ".join(["%s"] * len(cols_no_id))
    ins_sql = f"INSERT INTO `{cfg['remote']}` ({col_list}) VALUES ({placeholders})"
    data = [r[1:] for r in rows]  # id 제외

    with pymysql.connect(**REMOTE) as rc, rc.cursor() as rcur:
        rcur.executemany(ins_sql, data)

    new_last = rows[-1][0]
    write_last_id(offset_path, new_last)
    print(f"[{name}] uploaded {len(rows)} rows | last_id: {last_id} → {new_last}")

def main():
    # 순차 처리(충돌 방지): ADL → INOUT
    process_stream("ADL")
    process_stream("INOUT")

if __name__ == "__main__":
    main()
