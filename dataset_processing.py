import numpy as np
from sklearn.utils import shuffle
from sklearn.preprocessing import OneHotEncoder

def shuffle_ds(x_ds, t_ds) :
    idx = np.arange(x_ds.shape[0])
    np.random.shuffle(idx)

    x_ds = x_ds[idx]
    t_ds = t_ds[idx]
    
    return x_ds, t_ds
def oversample_ds(x_ds, t_ds):
    x_ret, t_ret = x_ds, t_ds
    unique, cnts = np.unique(t_ds, return_counts=True)
    num = max(cnts)
    for idx, label in enumerate(unique):
        label_idx = np.where(t_ds == label)[0]
        choice = np.random.choice(label_idx, num-cnts[idx])
        x_res = x_ds[choice]
        t_res = t_ds[choice]
        x_ret = np.concatenate((x_ret, x_res))
        t_ret = np.concatenate((t_ret, t_res))
    
    return shuffle_ds(x_ret, t_ret)
def undersample_ds(x_ds, t_ds):
    x_ret = []
    t_ret = []
    unique, cnts = np.unique(t_ds, return_counts=True)
    num = min(cnts)
    for idx, label in enumerate(unique):
        label_idx = np.where(t_ds == label)[0]
        choice = np.random.choice(label_idx, num, replace=False)
        x_ret.extend(x_ds[choice])
        t_ret.extend(t_ds[choice])

    x_ret = np.array(x_ret)
    t_ret = np.array(t_ret)
    
    return shuffle_ds(x_ret, t_ret)
def resample_ds(x_ds, t_ds, counts):
    x_ret = []
    t_ret = []
    unique, cnts = np.unique(t_ds, return_counts=True)
    num = counts
    for idx, label in enumerate(unique):
        label_idx = np.where(t_ds == label)[0]
        if len(label_idx) >= counts:
            choice = np.random.choice(label_idx, num, replace=False)
            x_ret.extend(x_ds[choice])
            t_ret.extend(t_ds[choice])
        else:
            choice = np.random.choice(label_idx, num-cnts[idx])
            x_ret.extend(x_ds[label_idx])
            t_ret.extend(t_ds[label_idx])
            x_ret.extend(x_ds[choice])
            t_ret.extend(t_ds[choice])
    
    x_ret = np.array(x_ret)
    t_ret = np.array(t_ret)
    
    return shuffle_ds(x_ret, t_ret)
def spec_augment_simple(spec: np.ndarray, num_mask=1, freq_masking_max_percentage=0.15, time_masking_max_percentage=0.3):
    """
    Applies SpecAugment (Frequency Masking + Time Masking) to a spectrogram.

    :param spec: Input spectrogram (numpy array)
    :param num_mask: Number of masks to apply
    :param freq_masking_max_percentage: Maximum percentage of frequency axis to mask
    :param time_masking_max_percentage: Maximum percentage of time axis to mask
    :return: Augmented spectrogram with frequency and time masking applied
    """
    spec = spec.copy()
    all_frames_num, all_freqs_num = spec.shape

    # **Apply Frequency Masking**
    for _ in range(num_mask):
        freq_percentage = np.random.uniform(0.0, freq_masking_max_percentage)
        num_freqs_to_mask = int(freq_percentage * all_freqs_num)
        f0 = np.random.randint(0, all_freqs_num - num_freqs_to_mask)
        spec[:, f0:f0 + num_freqs_to_mask] = 0

        # **Apply Time Masking**
        time_percentage = np.random.uniform(0.0, time_masking_max_percentage)
        num_frames_to_mask = int(time_percentage * all_frames_num)
        t0 = np.random.randint(0, all_frames_num - num_frames_to_mask)
        spec[t0:t0 + num_frames_to_mask, :] = 0

    return spec

def time_shift_spectrogram(spec: np.ndarray, shift_max=1):
    """
    Applies time shift to a spectrogram by rolling it along the time axis.

    :param spec: Input spectrogram (2D numpy array)
    :param shift_max: Maximum number of frames to shift
    :return: Time-shifted spectrogram
    """
    num_frames = spec.shape[1]  # Number of time frames in the spectrogram
    shift = np.random.randint(-shift_max, shift_max)

    shifted_spec = np.roll(spec, shift, axis=1)  # Shift along the time axis
    if shift > 0:
        shifted_spec[:, :shift] = 0  # Fill the left empty region with zeros
    else:
        shifted_spec[:, shift:] = 0  # Fill the right empty region with zeros
    return shifted_spec
def generate_augmented_spectrograms(spec: np.ndarray, shift_max: int):
    """
    Generates three versions of the spectrogram:
    1. Original spectrogram
    2. Spectrogram with SpecAugment (Random Masking)
    3. Time-shifted spectrogram

    :param spec: Input spectrogram (2D numpy array)
    :param shift_max: Maximum time shift in frames
    :return: (original_spec, masked_spec, shifted_spec)
    """
    masked_spec = spec_augment_simple(spec)  # Apply SpecAugment (Frequency & Time Masking)
    shifted_spec = time_shift_spectrogram(spec, shift_max)  # Apply Time Shift

    return masked_spec, shifted_spec
def spec_augment_ds(x_ds, t_ds, n_times=1, shift_max=2):
    """
    Applies data augmentation (Time Shift + SpecAugment) to the dataset.
    
    :param x_ds: Original spectrogram dataset (numpy array or list)
    :param t_ds: Corresponding labels
    :param n_times: Number of augmentation repetitions per sample
    :param shift_max: Maximum time shift in frames
    :return: Augmented dataset (x_ret, t_ret) with shuffled data
    """
    x_aug = []
    t_aug = []

    for x, t in zip(x_ds, t_ds):
        for _ in range(n_times):
            masked, shifted = generate_augmented_spectrograms(x, shift_max)
            
            x_aug.append(masked)   # Apply SpecAugment (Frequency + Time Masking)
            x_aug.append(shifted)  # Apply Time Shift
            t_aug.append(t)
            t_aug.append(t)

    # Merge original and augmented data
    x_ret = np.concatenate((x_ds, np.array(x_aug)), axis=0)
    t_ret = np.concatenate((t_ds, np.array(t_aug)), axis=0)

    # Shuffle dataset before returning
    return shuffle(x_ret, t_ret, random_state=42)
def onehot_ds(x, t, labels):
    encoder = OneHotEncoder(categories = [labels], sparse_output=False, handle_unknown='ignore')
    t_reshaped = np.array(t).reshape(-1, 1)
    t_onehot = encoder.fit_transform(t_reshaped)
    return x, t_onehot
def process_ds(x, t, resample_cnt=0, aug_cnt=0, shift_max=2):
    if resample_cnt:
        x, t = resample_ds(x, t, resample_cnt)
    if aug_cnt:
        x, t = spec_augment_ds(x, t, n_times=aug_cnt, shift_max=shift_max)
    x = x[..., np.newaxis]
    return x, t