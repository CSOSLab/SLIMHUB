#%%
import os
import sys

import numpy as np
import tensorflow as tf
import tensorflow_model_optimization as tfmot

from datetime import datetime

import logging

from dataset_processing import *
from sound_processing import *

# Set the seed value for experiment reproducibility.

seed = 64
np.random.seed(seed)
#%%
now = datetime.now()
address = sys.argv[1]
#%%
sr = 16000
wav_len = 16384
wav_hop = int(wav_len/2)
n_fft = 1024
n_hop = int(n_fft/2)
n_mels = 48

labels_to_use = np.array([
    'background',
    'hitting',
    'speech_tv',
    'airutils',
    'brushing',
    'peeing',
    'flushing',
    'flush_end',
    'cooking',
    'microwave',
    'watering_low',
    'watering_high',
])
generic_labels = np.array([
    'background',
    'hitting',
    'speech_tv',
    'airutils',
])

#%%
model_dir = os.path.join('programdata', 'models')
base_model_path = os.path.join(model_dir, 'base_model')
dataset_path = os.path.join(model_dir, "training_dataset.npz")

domain_model_path = os.path.join(model_dir, address)
#%%
model = tf.keras.models.load_model(base_model_path)
#%%
original_dataset = np.load(dataset_path)

#%%
x_train = original_dataset['x_train']
t_train = original_dataset['t_train']
x_test = original_dataset['x_test']
t_test = original_dataset['t_test']
x_val = original_dataset['x_val']
t_val = original_dataset['t_val']
# %%
domain_dataset_dir = os.path.join('programdata', 'datasets', address)
os.makedirs(domain_dataset_dir, exist_ok=True)

domain_dataset_initial_dir = os.path.join(domain_dataset_dir, 'initial')
domain_dataset_pseudo_dir = os.path.join(domain_dataset_dir, 'pseudo')

os.makedirs(domain_dataset_initial_dir, exist_ok=True)
os.makedirs(domain_dataset_pseudo_dir, exist_ok=True)

#%%
initial_files = glob.glob(domain_dataset_initial_dir + '/*/*.wav')
pseudo_files = glob.glob(domain_dataset_pseudo_dir + '/*/*.wav')

#%%
def mels_dataset(dataset_base_path, dataset_files, sr, wav_len, hop_len, n_mels, n_fft, n_hop, to_db=False):
    process_name = 'mels'
    category = os.path.split(dataset_base_path)[-1]

    name = f"{category}_{process_name}"

    x_all = []
    t_all = []
    locations = []

    for file_path in tqdm(dataset_files):
        # Extract location from the file path
        relative_path = os.path.relpath(file_path, dataset_base_path)  # e.g., "location/label/data.wav"
        location, label = os.path.split(os.path.dirname(relative_path))  # e.g., ("location", "label")
        
        if get_label(file_path) == label:  # Ensure the label matches
            for x, t in gen_mels_and_label(file_path, sr=sr, wav_len=wav_len, wav_hop=hop_len, n_mels=n_mels, n_fft=n_fft, n_hop=n_hop, to_db=to_db):
                x_all.append(x)
                t_all.append(t)
                locations.append(location)  # Store only location info

    x_all = np.array(x_all).astype(np.float32)
    t_all = np.array(t_all)
    locations = np.array(locations)  # Convert to numpy array for consistency

    return {
        'x': x_all, 
        't': t_all, 
        'name': name, 
        'location': locations,  # Store only location info
        'shape': x_all[0].shape, 
        'files': np.array(dataset_files)
    }

def save_ds(process, path):
    name = process['name']

    os.makedirs(path, exist_ok=True)
    
    np.savez_compressed(
        os.path.join(path, name),                    
        **process)
    # print(f"Dataset saved to {path}")

#%%
save_ds(mels_dataset(domain_dataset_initial_dir, initial_files, sr=sr, wav_len=wav_len, hop_len=wav_hop, n_mels=n_mels, n_fft=n_fft, n_hop=n_hop, to_db=True), domain_dataset_dir)

#%%
domain_dataset_path = os.path.join(domain_dataset_dir, 'initial_mels.npz')

domain_npzfile = np.load(domain_dataset_path)
# %%
domain_name = str(domain_npzfile['name']).split('_')[0]
# %%
x_domain = domain_npzfile['x']
t_domain = domain_npzfile['t']

# %%
domain_labels = np.unique(t_domain)
result = list(generic_labels)

# 2. labels_to_use에서 domain_labels에 있는 항목만 추가
filtered_labels_to_use = [label for label in labels_to_use if label in domain_labels and label not in generic_labels]
result.extend(filtered_labels_to_use)

# 3. domain_labels에서 새로 추가된 항목만 추가
additional_domain_labels = [label for label in domain_labels if label not in labels_to_use and label not in generic_labels]
result.extend(additional_domain_labels)

new_labels_to_use = np.array(result)

# %%
x_train = x_train[np.isin(t_train, new_labels_to_use)]
t_train = t_train[np.isin(t_train, new_labels_to_use)]

x_val = x_val[np.isin(t_val, new_labels_to_use)]
t_val = t_val[np.isin(t_val, new_labels_to_use)]

x_test = x_test[np.isin(t_test, new_labels_to_use)]
t_test = t_test[np.isin(t_test, new_labels_to_use)]

#%%
x_domain, t_domain = process_ds(x_domain, t_domain, resample_cnt=200, aug_cnt=1, shift_max=2)

x_train_domain = np.concatenate((x_train, x_domain))
t_train_domain = np.concatenate((t_train, t_domain))

# %%
def extract_windows(data: np.ndarray, time_steps: int = 32, overlap: float = 0.5, use_last: int = 128) -> np.ndarray:
    """
    Extract sliding windows from the last portion of a 2D feature sequence.
    Each window is shaped (feature_dim, time_steps, 1), suitable for CNN input.

    Parameters:
        data (np.ndarray): Input array with shape (time, feature_dim), e.g., (173, 48)
        time_steps (int): Length of each sliding window along the time axis (default: 32)
        overlap (float): Overlap ratio between windows (0.0 to <1.0), default is 0.5
        use_last (int): Number of most recent time steps to use (default: 128)

    Returns:
        np.ndarray: Array of shape (num_windows, feature_dim, time_steps, 1)
    """
    assert 0.0 <= overlap < 1.0, "overlap must be in the range [0.0, 1.0)."
    assert data.shape[0] >= use_last, "Input data is shorter than 'use_last'."

    # Use only the last 'use_last' time steps
    data = data[-use_last:]  # shape: (use_last, feature_dim)
    
    step_size = int(time_steps * (1 - overlap))
    windows = []

    for start in range(0, use_last - time_steps + 1, step_size):
        window = data[start:start + time_steps]  # shape: (time_steps, feature_dim)
        window = window.T  # transpose to (feature_dim, time_steps)
        window = np.expand_dims(window, axis=-1)  # add channel dimension: (feature_dim, time_steps, 1)
        windows.append(window)

    return np.stack(windows)
# %%
# Recursively find all .npz files
npz_files = glob.glob(os.path.join(domain_dataset_dir, "features", "**", "*.npz"), recursive=True)

x_train_background = []
t_train_background = []

for file_path in npz_files:
    try:
        with np.load(file_path) as npz:
            feature = npz['feature']  # make sure the key is 'feature'
            windows = extract_windows(feature)  # shape: (n, 48, 32, 1)
            x_train_background.append(windows)
            t_train_background.extend(['background'] * len(windows))
    except Exception as e:
        print(f"Failed to process {file_path}: {e}")

# Stack the feature arrays into one big array
x_train_background = np.concatenate(x_train_background, axis=0)  # shape: (total_windows, 48, 32, 1)
t_train_background = np.array(t_train_background)  # shape: (total_windows,)

# Sample a subset of the background data
num_samples = 400
total = len(x_train_background)

indices = np.random.choice(total, size=num_samples, replace=(total < num_samples))

x_train_background = x_train_background[indices]
t_train_background = t_train_background[indices]

# %%
x_train_domain = np.concatenate((x_train_domain, x_train_background))
t_train_domain = np.concatenate((t_train_domain, t_train_background))

#%%
x_train_domain, t_train_domain_oh = onehot_ds(x_train_domain, t_train_domain, new_labels_to_use)
x_val, t_val_oh = onehot_ds(x_val, t_val, new_labels_to_use)
x_test, t_test_oh = onehot_ds(x_test, t_test, new_labels_to_use)

# %%
base_encoder = tf.keras.models.Model(inputs=model.input, outputs=model.layers[-2].output, name='base')
#%%
# base_encoder와 클래스 수를 정의했다고 가정합니다.
num_classes = len(new_labels_to_use)  # 클래스 수를 올바르게 설정

# 새로운 분류기 레이어 생성
new_classifier = tf.keras.Sequential([
    tf.keras.layers.Dense(num_classes, activation='softmax')
])
new_classifier.build((None, base_encoder.output_shape[-1]))

# 새로운 분류기 모델에 양자화를 적용
quantize_model = tfmot.quantization.keras.quantize_model
qat_classifier = quantize_model(new_classifier)
# Functional API를 사용하여 base_encoder와 qat_classifier를 연결
inputs = base_encoder.input
x = base_encoder(inputs, training=False)
x = qat_classifier(x)

# 전체 모델 구성
transfer_model = tf.keras.Model(inputs=inputs, outputs=x)

for layer in base_encoder.layers:
    layer.trainable = False

# 모델 컴파일
transfer_model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=0.0001), 
                       loss='categorical_crossentropy', 
                       metrics=['accuracy'])

# 모델 요약 출력
transfer_model.summary()

# %%
# Train the model with your data
history = transfer_model.fit(x_train_domain, t_train_domain_oh, validation_data=(x_val, t_val_oh), epochs=50, batch_size=128)
# %%
# for layer in transfer_model.layers:
#     layer.trainable = True

# # Compile the model
# transfer_model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate= 1e-5), loss='categorical_crossentropy', metrics=['accuracy'])

# # Train the model with your data
# history = transfer_model.fit(x_train_all, t_train_all, validation_data=(x_val, t_val), epochs=10, batch_size=128)

#%%
# Save the model
saved_model_dir = os.path.join(domain_model_path)
transfer_model.save(saved_model_dir)

# %%
rep_ds = x_train_domain[:3000]
def representative_data_gen():
    for input_value in tf.data.Dataset.from_tensor_slices(rep_ds).batch(1).take(100):
        yield [input_value]

#%%

now = datetime.now()
converter_int8 = tf.lite.TFLiteConverter.from_keras_model(transfer_model)
converter_int8.optimizations = [tf.lite.Optimize.DEFAULT]
converter_int8.representative_dataset = representative_data_gen
converter_int8.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter_int8.inference_input_type = tf.int8  # or tf.uint8
converter_int8.inference_output_type = tf.int8  # or tf.uint8

tflite_model_int8 = converter_int8.convert()

tflite_model_int8_dir = os.path.join(model_dir, address+'.tflite')
# tflite_model_name = saved_model_name + '.tflite'
with open(tflite_model_int8_dir, 'wb') as f:
    f.write(tflite_model_int8)

logging.info(f"{address}: training time - {datetime.now() - now}")

# print("Conversion time: ", datetime.now() - now)
# %%
