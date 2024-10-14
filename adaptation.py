#%%
import os
import sys

import numpy as np
import tensorflow as tf
import tensorflow_model_optimization as tfmot

from datetime import datetime

import dataset_processing as dp

#%%
base_label = np.array([
    'brushing',
    'peeing',
    'flushing',
    'afterflushing',
    'airutils',
    'hitting',
    'microwave',
    'cooking',
    'speech',
    'tv',
    'watering1',
    'watering2',
    'background',
])

#%%
model_dir = 'programdata/models'
base_model_path = os.path.join(model_dir, 'base_model')
dataset_path = os.path.join(model_dir, "training_dataset.npz")
#%%
model = tf.keras.models.load_model(base_model_path)
model.summary()

#%%
original_dataset = np.load(dataset_path)
print(original_dataset.files)

#%%
x_train = original_dataset['x_train']
t_train = original_dataset['t_train']
x_test = original_dataset['x_test']
t_test = original_dataset['t_test']
x_val = original_dataset['x_val']
t_val = original_dataset['t_val']
# %%
domain_dataset_path = 'programdata/models/chl-toilet2_mels_48_1024_512_16384.npz'

domain_npzfile = np.load(domain_dataset_path)
print(domain_npzfile.files)
# %%
domain_name = str(domain_npzfile['name']).split('_')[0]
print(domain_name)
# %%
x_all = []
t_all = []
for key, data in domain_npzfile.items():
    if 'x_fold' in key:
        x_all.append(data)
    elif 't_fold' in key:
        t_all.append(data)
# %%
x_test_domain = x_all.pop(0)
t_test_domain= t_all.pop(0)

x_domain = np.concatenate(x_all)
t_domain = np.concatenate(t_all)

# %%
np.unique(t_domain, return_counts=True)

# %%
x_transfer = x_domain[np.where(t_domain == 'elecbrush')[0]]
t_transfer = t_domain[np.where(t_domain == 'elecbrush')[0]]

x_test_transfer = x_test_domain[np.where(t_test_domain == 'elecbrush')[0]]
t_test_transfer = t_test_domain[np.where(t_test_domain == 'elecbrush')[0]]

# %%
x_domain = x_domain[np.where(np.isin(t_domain, base_label))[0]]
t_domain = t_domain[np.where(np.isin(t_domain, base_label))[0]]

x_test_domain = x_test_domain[np.where(np.isin(t_test_domain, base_label))[0]]
t_test_domain = t_test_domain[np.where(np.isin(t_test_domain, base_label))[0]]
# for i in range(len(t_all[idx])):
#     x_all[idx][i] = librosa.power_to_db(x_all[idx][i], ref=np.max)

# %%
x_domain = np.concatenate([x_domain, x_transfer]) 
t_domain = np.concatenate([t_domain, t_transfer])

x_test_domain = np.concatenate([x_test_domain, x_test_transfer])
t_test_domain = np.concatenate([t_test_domain, t_test_transfer])

np.unique(t_domain, return_counts=True)

#%%
labels_to_use_new = np.append(base_label, 'elecbrush')

#%%
x_train_domain, t_train_domain = dp.process_ds(x_domain, t_domain, labels_to_use_new, resample_cnt=200, aug_cnt=1)
x_test_domain, t_test_domain = dp.process_ds(x_test_domain, t_test_domain, labels_to_use_new)

#%%
y_pred = model.predict(x_test_domain)

# %%
base_encoder = tf.keras.models.Model(inputs=model.input, outputs=model.layers[-2].output, name='base')

#%%
extra_column = np.zeros((t_train.shape[0], 1))  # 예를 들어, 0으로 채워진 열을 추가
t_train = np.hstack((t_train, extra_column))

extra_column = np.zeros((t_val.shape[0], 1))  # 예를 들어, 0으로 채워진 열을 추가
t_val = np.hstack((t_val, extra_column))

#%%
x_train_all = np.concatenate((x_train, x_train_domain))
t_train_all = np.concatenate((t_train, t_train_domain))

x_val_all = np.concatenate((x_val, x_test_domain))
t_val_all = np.concatenate((t_val, t_test_domain))

#%%
# base_encoder와 클래스 수를 정의했다고 가정합니다.
num_classes = model.layers[-1].output_shape[1] + 1  # 클래스 수를 올바르게 설정

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

#%%
for layer in transfer_model.layers:
    for weight in layer.weights:
        if 'min' in weight.name or 'max' in weight.name:
            print(f"Layer: {layer.name}, {weight.name}: {weight.numpy()}")
# %%
# Train the model with your data
now = datetime.now()

history = transfer_model.fit(x_train_all, t_train_all, validation_data=(x_val, t_val), epochs=30, batch_size=128)

print("Training time: ", datetime.now() - now)
# %%
# for layer in transfer_model.layers:
#     layer.trainable = True

# # Compile the model
# transfer_model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate= 1e-5), loss='categorical_crossentropy', metrics=['accuracy'])

# # Train the model with your data
# history = transfer_model.fit(x_train_all, t_train_all, validation_data=(x_val, t_val), epochs=10, batch_size=128)
# %%
rep_ds = x_train_all[:3000]
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

tflite_model_int8_dir = os.path.join(model_dir, domain_name+'_int8'+'.tflite')
# tflite_model_name = saved_model_name + '.tflite'
with open(tflite_model_int8_dir, 'wb') as f:
    f.write(tflite_model_int8)

print("Conversion time: ", datetime.now() - now)
# %%
print(tf.__version__)
# %%
