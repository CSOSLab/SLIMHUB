# Dean base service uuid
DEAN_UUID_BASE_SERVICE =                '4eab0000-6bef-11ee-b962-10012002809a'

# Device Configuration Service
DEAN_UUID_CONFIG_SERVICE =              '4eab0100-6bef-11ee-b962-10012002809a'
DEAN_UUID_CONFIG_DEVICE_TYPE_CHAR =     '4eab0101-6bef-11ee-b962-10012002809a'
DEAN_UUID_CONFIG_DEVICE_NAME_CHAR =     '4eab0102-6bef-11ee-b962-10012002809a'
DEAN_UUID_CONFIG_LOCATION_CHAR =        '4eab0103-6bef-11ee-b962-10012002809a'

# GridEye Service
DEAN_UUID_GRIDEYE_SERVICE =             '4eab0200-6bef-11ee-b962-10012002809a'
DEAN_UUID_GRIDEYE_PREDICTION_CHAR =     '4eab0201-6bef-11ee-b962-10012002809a'
DEAN_UUID_GRIDEYE_RAW_CHAR =            '4eab0202-6bef-11ee-b962-10012002809a'

# AAT Service
DEAN_UUID_AAT_SERVICE =                 '4eab0300-6bef-11ee-b962-10012002809a'
DEAN_UUID_AAT_ACTION_CHAR =             '4eab0301-6bef-11ee-b962-10012002809a'

# Environmental Service
DEAN_UUID_ENVIRONMENT_SERVICE =         '4eab0400-6bef-11ee-b962-10012002809a'
DEAN_UUID_ENVIRONMENT_SEND_CHAR =       '4eab0401-6bef-11ee-b962-10012002809a'
DEAN_UUID_ENVIRONMENT_RESERVED_CHAR =   '4eab0402-6bef-11ee-b962-10012002809a'

# Sound Service
DEAN_UUID_SOUND_SERVICE =               '4eab0500-6bef-11ee-b962-10012002809a'
DEAN_UUID_SOUND_PROCESSED_CHAR =        '4eab0501-6bef-11ee-b962-10012002809a'
DEAN_UUID_SOUND_RAW_CHAR =              '4eab0502-6bef-11ee-b962-10012002809a'

# Relay Service
DEAN_UUID_RELAY_SERVICE =               '4eab0600-6bef-11ee-b962-10012002809a'
DEAN_UUID_RELAY_GRID_CHAR =             '4eab0601-6bef-11ee-b962-10012002809a'
DEAN_UUID_RELAY_ENV_CHAR =              '4eab0602-6bef-11ee-b962-10012002809a'
DEAN_UUID_RELAY_AAT_CHAR =              '4eab0603-6bef-11ee-b962-10012002809a'

VER_UBINOS = True
if VER_UBINOS:
    # PAAR Ubinos
    DEAN_UUID_PAAR_SERVICE =            '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
    DEAN_UUID_PAAR_TX_CHAR =            '6e400002-b5a3-f393-e0a9-e50e24dcca9e'
    DEAN_UUID_PAAR_RX_CHAR =            '6e400003-b5a3-f393-e0a9-e50e24dcca9e'
else:
    # PAAR Service
    DEAN_UUID_PAAR_SERVICE =            '6e402650-b5a3-f393-e0a9-e50e24dcca9e'
    DEAN_UUID_PAAR_TX_CHAR =            '6e407f01-b5a3-f393-e0a9-e50e24dcca9e'
    DEAN_UUID_PAAR_RX_CHAR =            '6e407f02-b5a3-f393-e0a9-e50e24dcca9e'


dean_uuid_dict = {
    'base': {
        'service':          DEAN_UUID_BASE_SERVICE,
    },
    'config': {
        'service':          DEAN_UUID_CONFIG_SERVICE,
        'device_type':      DEAN_UUID_CONFIG_DEVICE_TYPE_CHAR,
        'device_name':      DEAN_UUID_CONFIG_DEVICE_NAME_CHAR,
        'location':         DEAN_UUID_CONFIG_LOCATION_CHAR
    },
    'grideye': {
        'service':          DEAN_UUID_GRIDEYE_SERVICE,
        'work':             DEAN_UUID_GRIDEYE_PREDICTION_CHAR,
        'raw':             DEAN_UUID_GRIDEYE_RAW_CHAR
    },
    'aat': {
        'service':          DEAN_UUID_AAT_SERVICE,
        'work':             DEAN_UUID_AAT_ACTION_CHAR
    },
    'environment': {
        'service':          DEAN_UUID_ENVIRONMENT_SERVICE,
        'work':             DEAN_UUID_ENVIRONMENT_SEND_CHAR,
        'raw':             DEAN_UUID_ENVIRONMENT_RESERVED_CHAR
    },
    'sound': {
        'service':          DEAN_UUID_SOUND_SERVICE,
        'work':             DEAN_UUID_SOUND_PROCESSED_CHAR,
        'raw':             DEAN_UUID_SOUND_RAW_CHAR
    },
    'relay': {
        'service':          DEAN_UUID_RELAY_SERVICE,
        'grid':             DEAN_UUID_RELAY_GRID_CHAR,
        'env':              DEAN_UUID_RELAY_ENV_CHAR,
        'aat':              DEAN_UUID_RELAY_AAT_CHAR
    }
}


dean_service_lookup = {
    DEAN_UUID_BASE_SERVICE:                 'base',
    
    DEAN_UUID_CONFIG_SERVICE:               'config',
    DEAN_UUID_CONFIG_DEVICE_TYPE_CHAR:      'type',
    DEAN_UUID_CONFIG_DEVICE_NAME_CHAR:      'id',
    DEAN_UUID_CONFIG_LOCATION_CHAR:         'location',

    DEAN_UUID_GRIDEYE_SERVICE:              'grideye',
    DEAN_UUID_GRIDEYE_PREDICTION_CHAR:      'work',
    DEAN_UUID_GRIDEYE_RAW_CHAR:             'raw',

    DEAN_UUID_AAT_SERVICE:                  'aat',
    DEAN_UUID_AAT_ACTION_CHAR:              'work',

    DEAN_UUID_ENVIRONMENT_SERVICE:          'environment',
    DEAN_UUID_ENVIRONMENT_SEND_CHAR:        'work',
    DEAN_UUID_ENVIRONMENT_RESERVED_CHAR:    'raw',

    DEAN_UUID_SOUND_SERVICE:                'sound',
    DEAN_UUID_SOUND_PROCESSED_CHAR:         'work',
    DEAN_UUID_SOUND_RAW_CHAR:               'raw',

    DEAN_UUID_RELAY_SERVICE:                'relay',
}