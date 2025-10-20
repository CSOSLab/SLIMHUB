import pymysql
import os

# Local DB configuration
LOCAL_DB = {
    'host': 'localhost',
    'port': 3306,
    'user': 'givemeadl',
    'password': 'rtlab!123',
    'database': 'adl_event',
    'charset': 'utf8mb4'
}

# Remote (central) DB configuration
REMOTE_DB = {
    'host': '155.230.186.52',
    'port': 4404,
    'user': 'Dr_Simon',
    'password': 'drsimon1234',
    'database': 'adl_raw',
    'charset': 'utf8mb4'
}

fixed_mac = "2C:CF:67:C6:2C:F6"
TABLE_NAME = 'rawdata_adl_chilgok'
LAST_ID_FILE = '/home/rtlab/SLIMHUB/ad_rawcron/log_dir/last_uploaded_id.txt'

def get_last_uploaded_id():
    if not os.path.exists(LAST_ID_FILE):
        with open(LAST_ID_FILE, 'w') as f:
            f.write('0')
        return 0
    with open(LAST_ID_FILE, 'r') as f:
            return int(f.read().strip())

def save_last_uploaded_id(last_id):
    with open(LAST_ID_FILE, 'w') as f:
        f.write(str(last_id))

def fetch_new_rows_from_local():
    last_id = get_last_uploaded_id()
    local_conn = pymysql.connect(**LOCAL_DB)
    local_cursor = local_conn.cursor()
    local_cursor.execute("""
        SELECT id, house_mac, location, created_time, event_sequence, adl, truth_value
        FROM event_adl
        WHERE id > %s
        ORDER BY id ASC
        """, (last_id,))
    rows = local_cursor.fetchall();
    local_cursor.close()
    local_conn.close()
    return rows


def upload_to_remote(rows):
    if not rows:
        print("No new record")
        return

    conn = pymysql.connect(**REMOTE_DB)
    central_cursor = conn.cursor()

    row_with_fixed_mac = ''
    insert_query = f'''
        INSERT INTO event_adl (
            house_mac, location, created_time, event_sequence, adl, truth_value
            ) VALUES (%s, %s, %s, %s, %s, %s)
        '''
    for row in rows:
        #print(len(row))
        #print(row)
        #print("fixed mac", fixed_mac)
        params = row[1:]
        try :
            central_cursor.execute(insert_query, params)  # Exclude 'id'
        except Exception as e:
            print("Insert failed : ", e)
        '''
        if len(row) == 15:
            row_with_fixed_mac = (fixed_mac,) + row[2:]
        elif len(row) == 13:
            row_with_fixed_mac = (fixed_mac,) + row
        try :
            central_cursor.execute(insert_query, row_with_fixed_mac)  # Exclude 'id'
        except Exception as e:
            print("Insert failed : ", e)
            print("data : ", row_with_fixed_mac)
        #print(row_with_fixed_mac)   
        '''
    conn.commit()
    central_cursor.close()
    conn.close()

    new_last_id = rows[-1][0]
    save_last_uploaded_id(new_last_id)
    print(f"uploaded {len(rows)} rows to central DB.")


def main():
    rows = fetch_new_rows_from_local()
    upload_to_remote(rows)

if __name__ == '__main__':
    main()
