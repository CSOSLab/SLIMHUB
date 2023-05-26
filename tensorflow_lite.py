import numpy as np
import tflite_runtime.interpreter as tflite

# tflite functions ------------------------------------------------------------
def set_interpreter(model_path):
    tflite_interpreter = tflite.Interpreter(model_path=model_path)

    tflite_interpreter.allocate_tensors()

    input_details = tflite_interpreter.get_input_details()[0]
    output_details = tflite_interpreter.get_output_details()[0]

    print("TFLite tensor allocated")

    # print("== Input details ==")
    # print("name:", input_details['name'])
    # print("shape:", input_details['shape'])
    # print("type:", input_details['dtype'])
    # print("index:", input_details['index'])

    # print("\n== Output details ==")
    # print("name:", output_details['name'])
    # print("shape:", output_details['shape'])
    # print("type:", output_details['dtype'])
    # print("index:", input_details['index'])

    return tflite_interpreter


def inference(tflite_interpreter, input_data):
    input_details = tflite_interpreter.get_input_details()[0]
    output_details = tflite_interpreter.get_output_details()[0]

    input_data = np.expand_dims(input_data, axis=0)

    tflite_interpreter.set_tensor(input_details['index'], input_data)

    tflite_interpreter.invoke()

    tflite_model_predictions = tflite_interpreter.get_tensor(output_details['index'])

    return tflite_model_predictions[0]