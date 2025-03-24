# %%
import os
import pathlib
import glob
import random

# import matplotlib.pyplot as plt
import numpy as np

import soundfile as sf
import librosa
from tqdm import tqdm

from scipy.io import wavfile
import scipy.io

import math

# %%
def get_label(file_path):
    parts = file_path.split(os.path.sep)
    return parts[-2]

def get_label_id(labels, label):
    return np.where(labels == label)[0][0]

def get_label_onehot(labels, label):
    arr = np.zeros(len(labels))
    arr[get_label_id(labels, label)] = 1
    return arr

# %%
def get_spectrogram_librosa(wav_data, n_fft, n_hop):

    spec = librosa.stft(y=wav_data, n_fft=n_fft, hop_length=n_hop)

    # spec = spec[..., np.newaxis]

    return spec

# %%
def get_mel_spectrogram_librosa(wav_data, sr, n_mels, n_fft, n_hop):

    mels = librosa.feature.melspectrogram(
        y=wav_data, sr=sr, n_mels=n_mels, n_fft=n_fft, hop_length=n_hop)

    mels = mels[:,:-1]
    # mels = mels[..., np.newaxis]

    return mels

# %%
def get_mfcc_librosa(wav_data, sr, n_mfcc, n_mels, n_fft, n_hop):

    mfcc = librosa.feature.mfcc(
        y=wav_data, sr=sr, n_mfcc=n_mfcc, n_mels=n_mels, n_fft=n_fft, hop_length=n_hop)

    mfcc = mfcc[:,:-1]
    # mels = mels[..., np.newaxis]

    return mfcc

# %%
def get_spectrogram(wav_data, n_fft, n_hop, envelop=0.0, env_ratio=0.0):
    spec = []
    
    current_idx = 0
    window = np.hanning(n_fft)

    wav_data = np.pad(wav_data, (int(n_fft/2), 0), 'constant', constant_values=0)

    max_power = 0
    while current_idx+n_fft <= wav_data.shape[0]:
        rfft = np.fft.rfft(wav_data[current_idx:current_idx+n_fft]*window)
        power_spectrum = np.abs(rfft) ** 2
        spec.append(power_spectrum)
        current_idx = current_idx + n_hop

        frame_power = np.sum(power_spectrum)
        if max_power < frame_power:
            max_power = frame_power
    
    if envelop:
        for frame in spec:
            if np.sum(frame) < max_power*envelop:
                frame = frame*env_ratio
    
    return np.array(spec).T.astype(np.float32)

# %%
def get_mel_spectrogram(wav_data, sr, n_mels, n_fft, n_hop, to_db=False, envelop=0.0, env_ratio=0.0):
    mel_filter_weights = librosa.filters.mel(sr=sr, n_fft=n_fft, n_mels=n_mels, fmin=0.0, fmax=8000, htk=False, norm='slaney')
    mel_spec = []
    
    for spec in get_spectrogram(wav_data, n_fft, n_hop, envelop=envelop, env_ratio=env_ratio).T:
        mel_spec.append(np.dot(spec, mel_filter_weights.T))
    
    if to_db:
        return librosa.power_to_db(np.array(mel_spec)).T.astype(np.float32)
    else:
        return np.array(mel_spec).T.astype(np.float32)

# %%
def get_mfcc(wav_data, sr, n_mfcc, n_mels, n_fft, n_hop, envelop=0.0, env_ratio=0.0):
    def dct4(input):
        output = np.zeros(n_mfcc)
        for k in range(n_mfcc):
            sum = 0.0
            for n in range(n_mfcc):
                if n == 0:
                    alpha = 1.0 / math.sqrt(2)
                else:
                    alpha = 1.0
                theta = (math.pi * (2 * n + 1) * k) / (2 * n_mfcc)
                sum += input[n] * math.cos(theta) * alpha
            output[k] = sum * math.sqrt(2.0 / n_mfcc)
        return output
    
    def dct_type4(input_data, n_mfcc=n_mfcc):
        N = len(input_data)
        output_data = np.zeros(n_mfcc)

        for k in range(n_mfcc):
            for n in range(N):
                output_data[k] += input_data[n] * np.cos((np.pi / N) * (n + 0.5) * k)

        return output_data
    
    def dct_type2(input_data, n_mfcc=n_mfcc):
        N = len(input_data)
        output_data = np.zeros(n_mfcc)

        for k in range(n_mfcc):
            sum_val = 0.0
            for n in range(N):
                sum_val += input_data[n] * np.cos((np.pi / N) * (n + 0.5) * k)

            if k == 0:
                output_data[k] = sum_val * np.sqrt(1.0 / N)
            else:
                output_data[k] = sum_val * np.sqrt(2.0 / N)

        return output_data


    mfcc = []
    for mels in get_mel_spectrogram(wav_data, sr, n_mels, n_fft, n_hop, to_db=True, envelop=envelop, env_ratio=env_ratio).T:
        # mfcc.append(dct_type2(np.log1p(spec)))
        mfcc.append(dct_type2(mels))
        # mfcc.append(dct_type4(spec))
    
    return np.array(mfcc).T.astype(np.float32)

# %%
def wav_read_librosa(file_path, sr, wav_len):
    wav_data, sr = librosa.load(file_path, sr=sr)
    wav_samples = wav_len
    if wav_data.shape[0] < wav_samples:
        pad = int(wav_samples-wav_data.shape[0])
        # pad_front = random.randint(0, pad-1)
        # pad_front = int(pad/2)
        pad_front = 0
        pad_end = int(pad-pad_front)
        wav_data = np.pad(wav_data, (pad_front, pad_end), 'constant', constant_values=0)
    return wav_data

#%%
def wav_read_scipy(file_path, wav_len):
    sr, wav_data = wavfile.read(file_path)
    wav_samples = wav_len
    if wav_data.shape[0] < wav_samples:
        pad = int(wav_samples-wav_data.shape[0])
        # pad_front = random.randint(0, pad-1)
        # pad_front = int(pad/2)
        pad_front = 0
        pad_end = int(pad-pad_front)
        wav_data = np.pad(wav_data, (pad_front, pad_end), 'constant', constant_values=0)
    return wav_data

# %%
def gen_wavform_and_label(file_path, sr, wav_len, wav_hop, return_label=True):
    window_len = wav_len
    window_hop = wav_hop
    wav_data = wav_read_librosa(file_path, sr=sr, wav_len=wav_len)
    if return_label:
        label = get_label(file_path)

    idx = 0
    while (idx+window_len) <= wav_data.shape[0]:
        wavform = wav_data[idx:idx+window_len]
        idx = idx + window_hop
        if return_label:
            yield wavform, label
        else:
            yield wavform

# %%
def gen_mels_and_label(file_path, sr, wav_len, wav_hop, n_mels, n_fft, n_hop, to_db=False, return_label=True, energy_threshold=0.0):
    window_len = wav_len
    window_hop = wav_hop
    wav_data = wav_read_librosa(file_path, sr=sr, wav_len=wav_len)
    # label = get_label_id(labels, get_label(file_path))
    if return_label:
        label = get_label(file_path)

    idx = 0
    while (idx+window_len) <= wav_data.shape[0]:
        wav_split = wav_data[idx:idx+window_len]

        # rms_energy = np.sqrt(np.mean(wav_split**2))
        
        # # Set wav_split to 0 if RMS energy is below the threshold
        # if rms_energy < energy_threshold:
        #     wav_split = np.zeros_like(wav_split)

        mels = get_mel_spectrogram(wav_split, sr=sr, n_mels=n_mels, n_fft=n_fft, n_hop=n_hop, to_db=to_db)
        idx = idx + window_hop
        if return_label:
            yield mels, label
        else:
            yield mels

#%%
def gen_mfcc_and_label(file_path, sr, wav_len, wav_hop, n_mfcc, n_mels, n_fft, n_hop, envelop=0.0, env_ratio=0.0, return_label=True):
    window_len = wav_len
    window_hop = wav_hop
    wav_data = wav_read_librosa(file_path, sr=sr, wav_len=wav_len)
    # label = get_label_id(labels, get_label(file_path))
    if return_label:
        label = get_label(file_path)

    idx = 0
    while (idx+window_len) <= wav_data.shape[0]:
        mfcc = get_mfcc(wav_data[idx:idx+window_len], sr=sr, n_mfcc=n_mfcc, n_mels=n_mels ,n_fft=n_fft, n_hop=n_hop, envelop=envelop, env_ratio=env_ratio)
        idx = idx + window_hop
        if return_label:
            yield mfcc, label
        else:
            yield mfcc

# %%
def gen_wavfrom_and_label_int16(file_path, labels, sr=16000, wav_len=1, wav_hop=1):
    window_len = wav_len
    window_hop = wav_hop
    wav_data = wav_read_librosa(file_path, sr=sr, wav_len=wav_len)
    wav_data = wav_data*32768
    wav_data = wav_data.astype(np.int16)
    label = get_label_id(labels, get_label(file_path))
    idx = 0
    while (idx+window_len) <= wav_data.shape[0]:
        wavform = wav_data[idx:idx+window_len]
        idx = idx + window_hop
        yield wavform, label

# %%
def gen_wavfrom_and_label_scipy(file_path, labels, sr=16000, wav_len=1, wav_hop=1):
    window_len = wav_len
    window_hop = wav_hop
    wav_data = wav_read_scipy(file_path, wav_len=wav_len)
    label = get_label_id(labels, get_label(file_path))
    idx = 0
    while (idx+window_len) <= wav_data.shape[0]:
        wavform = wav_data[idx:idx+window_len]
        idx = idx + window_hop
        yield wavform, label
# %%
