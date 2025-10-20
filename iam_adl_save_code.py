# multi_file_db_insert.py
import os
import json
from datetime import datetime
import pymysql

# ====== 설정 ======
DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'givemeadl',
    'password': 'rtlab!123',
    'database': 'adl_event'
}

TABLE_NAME = 'event_adl'

today_str = datetime.now().strftime('%Y-%m-%d')

FILE1 = f'/home/rtlab/SLIMHUB/data/LIVING/DE&N/F3:7D:01:38:75:C1/inference/debugstr/{today_str}.txt'
FILE2 = f'/home/rtlab/SLIMHUB/data/KITCHEN/DE&N/DC:1C:49:F9:A0:83/inference/debugstr/{today_str}.txt'
FILE3 = f'/home/rtlab/SLIMHUB/data/ENTRY/DE&N/F3:07:B6:5C:BD:92/inference/rawdata/2025-03-28.txt'
#FILE2 = f'/home/hmkang/SLIMHUB/data/KITCHEN/DE&N/E9:D4:F1:33:3D:BC/inference/debugstr/{today_str}.txt'
#FILE3 = f'/home/hmkang/SLIMHUB/data/BEDROOM/DE&N/E2:E9:45:F9:91:71/inference/rawdata/{today_str}.txt'
FILE4 = f'/home/rtlab/SLIMHUB/data/TOILET/DE&N/DB:3A:07:BB:C2:69/inference/rawdata/{today_str}.txt'
#FILE5 = f'/home/hmkang/SLIMHUB/data/LIVING/DE&N/ED:5A:F2:AF:BF:65/inference/rawdata/{today_str}.txt'
#FILE6 = '/home/hmkang/SLIMHUB/data/KITCHEN/DE&N/macaddress/inference/rawdata/2025-03-25_6.txt'

#FILE_LIST = [FILE1, FILE2, FILE3, FILE4, FILE5]
FILE_LIST = [FILE1, FILE2, FILE3, FILE4]

TRACKER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'log_dir')

def get_last_line_index(file_path):
    base_name = os.path.basename(file_path)
    mac_part = extract_location(file_path)
    tracker_file = os.path.join(TRACKER_DIR, f'{mac_part}_{base_name}.line')
    if not os.path.exists(tracker_file):
        return 1
    with open(tracker_file, 'r') as f:
        return int(f.read().strip() or 1)

def update_last_line_index(file_path, index):
    base_name = os.path.basename(file_path)
    mac_part = extract_location(file_path)
    tracker_file = os.path.join(TRACKER_DIR, f'{mac_part}_{base_name}.line')
    with open(tracker_file, 'w') as f:
        f.write(str(index))

def extract_location(file_path):
    parts = file_path.split('/')
    if 'DE&N' in parts:
        idx = parts.index('DE&N')
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return 'unknown'
'''
def get_last_line_index(file_path):
    tracker_file = os.path.join(TRACKER_DIR, os.path.basename(file_path) + '.line')
    if not os.path.exists(tracker_file):
        return 0
    with open(tracker_file, 'r') as f:
        return int(f.read().strip() or 0)

def update_last_line_index(file_path, index):
    tracker_file = os.path.join(TRACKER_DIR, os.path.basename(file_path) + '.line')
    with open(tracker_file, 'w') as f:
        f.write(str(index))

def extract_location(file_path):
    parts = file_path.split('/')
    if 'DE&N' in parts:
        idx = parts.index('DE&N')
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return 'unknown'
'''
def _to_dt(ts: str):
    """'2025-03-31 16:13:16' 같은 문자열을 datetime으로. 실패 시 그대로 반환."""
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            pass
    return ts  # PyMySQL이 문자열도 TIMESTAMP로 넣어줄 수 있음

def _to_float(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def parse_line_to_row(line, _location_unused=None):
    """
    라인별 JSON을 읽어 DB 행(list)로 변환.
    매핑:
      house_mac   = NULL
      location    = device
      created_time= timestamp
      event_sequence = sequence (양끝 공백 제거)
      adl         = NULL
      truth_value = truth
    """
    s = line.strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None

    device = obj.get("device")
    ts     = _to_dt(obj.get("timestamp"))
    seq    = (obj.get("sequence") or "").strip() or None
    adl    = obj.get("ADL")
    truth  = _to_float(obj.get("truth"))

    # 필수값 체크: device, timestamp는 있어야 함
    if not device or not ts:
        return None

    # 컬럼 순서에 맞춰 반환
    return [
        None,        # house_mac -> NULL
        device,      # location
        ts,          # created_time
        seq,         # event_sequence
        adl,        # adl -> NULL
        truth,       # truth_value
    ]

def insert_rows(rows):
    if not rows:
        return
    conn = pymysql.connect(**DB_CONFIG)

    try:
        with conn.cursor() as cursor:
            sql = f"""
            INSERT INTO {TABLE_NAME}
              (house_mac, location, created_time, event_sequence, adl, truth_value)
            VALUES (%s, %s, %s, %s, %s, %s)
            """
            cursor.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()

def process_file(file_path):
    if not os.path.exists(file_path):
        return 0

    location = extract_location(file_path)

    # 그대로 readlines() 사용 (라인바이라인 대용량 최적화는 나중에)
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    last_index = get_last_line_index(file_path) or 0
    new_lines = lines[last_index:]

    # ✅ parse_line_to_row를 한 번만 호출하도록 변경(중복 파싱 제거)
    rows = []
    for line in new_lines:
        row = parse_line_to_row(line, location)
        if row:
            rows.append(row)
    insert_rows(rows)   
    #print(rows)
    # ✅ DB 입력이 성공했을 때만 오프셋 업데이트(데이터 유실 방지)
    try:
        insert_rows(rows)
    except Exception:
        # 실패 시 오프셋을 갱신하지 않음 → 재시도 시 같은 구간 다시 처리
        raise
    else:
        update_last_line_index(file_path, len(lines))
        return len(rows)


if __name__ == '__main__':
    for file_path in FILE_LIST:
        print(file_path)
        process_file(file_path)
