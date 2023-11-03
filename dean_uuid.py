dean_uuid_dict = {
    'base':                 '4eab0000-6bef-11ee-b962-10012002809a',
    'config': {
        'service':          '4eab0100-6bef-11ee-b962-10012002809a',
        'device_type':      '4eab0101-6bef-11ee-b962-10012002809a',
        'device_name':      '4eab0102-6bef-11ee-b962-10012002809a',
        'location':         '4eab0103-6bef-11ee-b962-10012002809a'
    },
    'grid': {
        'service':          '4eab0000-ffff-0001-0002-10012002809a',
        'prediction':       '4eab0000-ffff-0001-0002-10012002809a',
        'raw_streaming':    '4eab0000-ffff-0001-0001-10012002809a'
    },
    'aat': {
        'service':          '4eab0000-ffff-0003-0005-10012002809a',
        'action':           '4eab0000-ffff-0003-0005-10012002809a'
    },
    'env': {
        'service':          '4eab0000-ffff-0001-0003-10012002809a',
        'send':             '4eab0000-ffff-0001-0003-10012002809a',
        'reserved':         '4eab0000-ffff-0001-0003-10012002809a'
    },
    'sound': {
        'service':          '4eab0000-ffff-0001-0004-10012002809a',
        'processed':        '4eab0000-ffff-0001-0004-10012002809a',
        'raw_streaming':    '4eab0000-ffff-0001-00f4-10012002809a'
    },
    'relay': {
        'service':          '4eab0000-ffff-0001-ff00-10012002809a',
        'grid':             '4eab0000-ffff-0001-ff01-10012002809a',
        'env':              '4eab0000-ffff-0001-ff02-10012002809a',
        'aat':              '4eab0000-ffff-0001-ff03-10012002809a'
    }
}

dean_service_lookup = {
    '4eab0000-6bef-11ee-b962-10012002809a' : 'base',
    '4eab0100-6bef-11ee-b962-10012002809a' : 'config',
    '4eab0000-ffff-0001-0002-10012002809a' : 'grideye',
    '4eab0000-ffff-0003-0005-10012002809a' : 'aat',
    '4eab0000-ffff-0001-0003-10012002809a' : 'environment',
    '4eab0000-ffff-0001-0004-10012002809a' : 'sound',
    '4eab0000-ffff-0001-ff00-10012002809a' : 'relay',
}

BLE_UUID_DEAN_BASE =                '4eab0000-6bef-11ee-b962-10012002809a'

# Device Configuration Service

BLE_UUID_CONFIG_SERVICE =              '4eab0100-6bef-11ee-b962-10012002809a'
BLE_UUID_CONFIG_DEVICE_NAME_CHAR =     '4eab0101-6bef-11ee-b962-10012002809a'
BLE_UUID_CONFIG_DEVICE_TYPE_CHAR =     '4eab0102-6bef-11ee-b962-10012002809a'
BLE_UUID_CONFIG_LOCATION_CHAR =        '4eab0103-6bef-11ee-b962-10012002809a'

# GridEye Service

BLE_UUID_GRID_SERVICE =             '4eab0000-ffff-0001-0002-10012002809a'
BLE_UUID_GRID_PREDICTION_CHAR =     '4eab0000-ffff-0001-0002-10012002809a'
BLE_UUID_GRID_RAW_STREAMING_CHAR =  '4eab0000-ffff-0001-0001-10012002809a'

# AAT Service

BLE_UUID_AAT_SERVICE =              '4eab0000-ffff-0003-0005-10012002809a'
BLE_UUID_AAT_ACTION_CHAR =          '4eab0000-ffff-0003-0005-10012002809a'

# Environmental Service

BLE_UUID_ENV_SERVICE =              '4eab0000-ffff-0001-0003-10012002809a'
BLE_UUID_ENV_SEND_CHAR =            '4eab0000-ffff-0001-0003-10012002809a'
BLE_UUID_ENV_RESERVED_CHAR =        '4eab0000-ffff-0001-0003-10012002809a'

# Sound Service

BLE_UUID_SND_SERVICE =              '4eab0500-6bef-11ee-b962-10012002809a'
BLE_UUID_SND_PROCESSED_CHAR =       '4eab0501-6bef-11ee-b962-10012002809a'
BLE_UUID_SND_RAW_STREAMING_CHAR =   '4eab0502-6bef-11ee-b962-10012002809a'

# Relay Service

BLE_UUID_RELAY_SERVICE =            '4eab0000-ffff-0001-ff00-10012002809a'
BLE_UUID_RELAY_GRID_CHAR =          '4eab0000-ffff-0001-ff01-10012002809a'
BLE_UUID_RELAY_ENV_CHAR =           '4eab0000-ffff-0001-ff02-10012002809a'
BLE_UUID_RELAY_AAT_CHAR =           '4eab0000-ffff-0001-ff03-10012002809a'


VER_UBINOS = True
if VER_UBINOS:
    # PAAR Ubinos

    BLE_UUID_PAAR_SERVICE = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
    BLE_UUID_PAAR_TX_CHAR = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'
    BLE_UUID_PAAR_RX_CHAR = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'
else:
    # PAAR Service

    BLE_UUID_PAAR_SERVICE = '6e402650-b5a3-f393-e0a9-e50e24dcca9e'
    BLE_UUID_PAAR_TX_CHAR = '6e407f01-b5a3-f393-e0a9-e50e24dcca9e'
    BLE_UUID_PAAR_RX_CHAR = '6e407f02-b5a3-f393-e0a9-e50e24dcca9e'