import numpy as np

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
def spec_augment_simple(spec: np.ndarray, num_mask=2, freq_masking_max_percentage=0.15, time_masking_max_percentage=0.3):
      spec = spec.copy()
      for i in range(num_mask):
         all_frames_num, all_freqs_num = spec.shape
         freq_percentage = np.random.uniform(0.0, freq_masking_max_percentage)
         
         num_freqs_to_mask = int(freq_percentage * all_freqs_num)
         f0 = np.random.uniform(low=0.0, high=all_freqs_num - num_freqs_to_mask)
         f0 = int(f0)
         spec[:, f0:f0 + num_freqs_to_mask] = 0

         time_percentage = np.random.uniform(0.0, time_masking_max_percentage)
         
         num_frames_to_mask = int(time_percentage * all_frames_num)
         t0 = np.random.uniform(low=0.0, high=all_frames_num - num_frames_to_mask)
         t0 = int(t0)
         spec[t0:t0 + num_frames_to_mask, :] = 0
      return spec
def spec_augment_ds(x_ds, t_ds, n_times=1):
   x_aug = []
   t_aug = []
   for x, t in zip(x_ds, t_ds):
      for i in range(n_times):
         x_aug.append(spec_augment_simple(x, num_mask=1))
         t_aug.append(t)
   x_ret = np.concatenate((x_ds, np.array(x_aug)))
   t_ret = np.concatenate((t_ds, np.array(t_aug)))

   return shuffle_ds(x_ret, t_ret)
from sklearn.preprocessing import OneHotEncoder
def process_ds(x, t, labels, resample_cnt=0, aug_cnt=0, ):
    if resample_cnt:
        x, t = resample_ds(x, t, resample_cnt)
    if aug_cnt:
        x, t = spec_augment_ds(x, t, n_times=aug_cnt)

    x = x[..., np.newaxis]
    encoder = OneHotEncoder(categories = [labels], sparse_output=False, handle_unknown='ignore')
    t_reshaped = np.array(t).reshape(-1, 1)
    t_onehot = encoder.fit_transform(t_reshaped)
    return x, t_onehot