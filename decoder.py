import numpy as np

import os
import soundfile as sf
import argparse
import sys
import glob

class Decoder:
    DEFAULT_CHUNK_SIZE = 259
    DEFAULT_SAMPLE_RATE = 16000

    # Intel ADPCM step variation table
    INDEX_TABLE = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8,]

    # ADPCM step size table
    STEP_SIZE_TABLE = [7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209,
                    230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358,
                    5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767]

    def __init__(self):
        self.chunk_size = self.DEFAULT_CHUNK_SIZE
        self.sample_rate = self.DEFAULT_SAMPLE_RATE


    def adpcm_decode(self, adpcm: list):
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
                step = self.STEP_SIZE_TABLE[index]

                # /* Step 2 - Find new index value (for later) */
                index = index + self.INDEX_TABLE[delta]
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

    def decode_file(self, dat_path):
        pcm = []
        
        with open(dat_path, "rb") as f:
            while True:
                adpcm_chunk = f.read(self.chunk_size)
                if not adpcm_chunk:
                    break

                pcm_frame = self.adpcm_decode(adpcm_chunk)
                pcm.extend(pcm_frame)
        
        return pcm

def save_wav(data, file_dir):
    sf.write(file_dir[:-4]+'.wav', data, 16000, 'PCM_16')

if __name__ == "__main__":
    decoder = Decoder()
    parser = argparse.ArgumentParser(description="ADPCM Decoder")
    parser.add_argument('-f', '--file', nargs=1)
    parser.add_argument('-d', '--dir', nargs=1)

    if len(sys.argv)==1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    if args.file:
        file_dir = str(args.file[0])
        data = decoder.decode_file(file_dir)
        save_wav(data, file_dir)

    if args.dir:
        dir_path = str(args.dir[0])
        files = glob.glob(dir_path+'/*')
        for file in files:
            data = decoder.decode_file(file)
            save_wav(data, file)