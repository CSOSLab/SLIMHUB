import numpy as np

import soundfile as sf
import librosa

# Intel ADPCM step variation table
INDEX_TABLE = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8,]

# ADPCM step size table
STEP_SIZE_TABLE = [7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209,
                   230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358,
                   5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767]


def adpcm_decode(adpcm: list):
    # Allocate output buffer
    pcm = []

    # The first 2 bytes of ADPCM frame are the predicted value
    valuePredicted = int.from_bytes(adpcm[:2], byteorder='big', signed=True)
    # The 3rd byte is the index value
    index = int(adpcm[2])
    data = adpcm[3:]

    if (index < 0):
        index = 0
    if (index > 88):
        index = 88

    for value in data:
        deltas = [(value >> 4) & 0x0f, value & 0x0f]
        for delta in deltas:
            # Update step value
            step = STEP_SIZE_TABLE[index]

            # /* Step 2 - Find new index value (for later) */
            index = index + INDEX_TABLE[delta]
            if index < 0:
                index = 0
            if index > 88:
                index = 88

            # /* Step 3 - Separate sign and magnitude */
            sign = delta & 8
            delta = delta & 7

            # /* Step 4 - Compute difference and new predicted value */
            diff = (step >> 3)
            if (delta & 4) > 0:
                diff += step
            if (delta & 2) > 0:
                diff += step >> 1
            if (delta & 1) > 0:
                diff += step >> 2

            if sign > 0:
                valuePredicted = valuePredicted-diff
            else:
                valuePredicted = valuePredicted+diff

            # /* Step 5 - clamp output value */
            if valuePredicted > 32767:
                valuePredicted = 32767
            elif valuePredicted < -32768:
                valuePredicted = -32768

            valuePredicted = np.float32(valuePredicted/32768)
            # /* Step 7 - Output value */
            pcm.append(valuePredicted)

    return pcm


def save_wav(output_path, input, sr):
    sf.write(output_path, input, sr, 'PCM_16')
    print(output_path, 'saved')


def get_mfcc(input, sr, n_mfcc, n_mels, n_fft, n_hop):
    input_pcm = np.array(input, dtype=np.float32)
    mfcc = librosa.feature.mfcc(y=input_pcm, sr=sr, n_mfcc=n_mfcc, n_mels=n_mels, n_fft=n_fft, hop_length=n_hop)
    mfcc = mfcc[:,:-1]
    mfcc = mfcc[..., np.newaxis]

    return mfcc