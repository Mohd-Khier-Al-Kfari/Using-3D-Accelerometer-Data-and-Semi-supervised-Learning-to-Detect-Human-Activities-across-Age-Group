import tensorflow as tf

__author__ = "C. I. Tang"
__copyright__ = "Copyright (C) 2021 C. I. Tang"

"""
Complementing the work of Tang et al.: SelfHAR: Improving Human Activity Recognition through Self-training with Unlabeled Data
@article{tang2021selfhar,
  title={SelfHAR: Improving Human Activity Recognition through Self-training with Unlabeled Data},
  author={Tang, Chi Ian and Perez-Pozuelo, Ignacio and Spathis, Dimitris and Brage, Soren and Wareham, Nick and Mascolo, Cecilia},
  journal={Proceedings of the ACM on Interactive, Mobile, Wearable and Ubiquitous Technologies},
  volume={5},
  number={1},
  pages={1--30},
  year={2021},
  publisher={ACM New York, NY, USA}
}

Access to Article:
    https://doi.org/10.1145/3448112
    https://dl.acm.org/doi/abs/10.1145/3448112

Contact: cit27@cl.cam.ac.uk
"""
def create_1d_conv_core_model(input_shape, model_name="base_model"):
    """
    Create the base model for activity recognition
    Reference (TPN model):
        Saeed, A., Ozcelebi, T., & Lukkien, J. (2019). Multi-task self-supervised learning for human activity detection. Proceedings of the ACM on Interactive, Mobile, Wearable and Ubiquitous Technologies, 3(2), 1-30.
    Architecture:
        Input
        -> Conv 1D: 32 filters, 24 kernel_size, relu, L2 regularizer
        -> Dropout: 10%
        -> Conv 1D: 64 filters, 16 kernel_size, relu, L2 regularizer
        -> Dropout: 10%
        -> Conv 1D: 96 filters, 8 kernel_size, relu, L2 regularizer
        -> Dropout: 10%
        -> Global Maximum Pooling 1D
    
    Parameters:
        input_shape
            the input shape for the model, should be (window_size, num_channels)
    
    Returns:
        model (tf.keras.Model)
    """

    inputs = tf.keras.Input(shape=input_shape, name='input')
    x = inputs
    x = tf.keras.layers.Conv1D(
            32, 24,
            activation='relu',
            kernel_regularizer=tf.keras.regularizers.l2(l=1e-4)
        )(x)
    x = tf.keras.layers.Dropout(0.1)(x)

    x = tf.keras.layers.Conv1D(
            64, 16,
            activation='relu',
            kernel_regularizer=tf.keras.regularizers.l2(l=1e-4),
        )(x)
    x = tf.keras.layers.Dropout(0.1)(x)
    
    x = tf.keras.layers.Conv1D(
        96, 8,
        activation='relu',
        kernel_regularizer=tf.keras.regularizers.l2(l=1e-4),
        )(x)
    x = tf.keras.layers.Dropout(0.1)(x)
    
    x = tf.keras.layers.GlobalMaxPool1D(data_format='channels_last', name='global_max_pooling1d')(x)

    return tf.keras.Model(inputs, x, name=model_name)


def extract_core_model(composite_model):
    return composite_model.layers[1]

def extract_har_model(multitask_model, optimizer, output_index=-1, model_name="har"):
    model = tf.keras.Model(inputs=multitask_model.inputs, outputs=multitask_model.outputs[output_index], name=model_name)

    model.compile(
        optimizer=optimizer,
        loss=tf.keras.losses.CategoricalCrossentropy(),
        metrics=[tf.keras.metrics.CategoricalAccuracy(name="categorical_accuracy"), tf.keras.metrics.AUC(name="auc"), tf.keras.metrics.Precision(name="precision"), tf.keras.metrics.Recall(name="recall")]
    )

    return model

def set_freeze_layers(model, num_freeze_layer_index=None):
    if num_freeze_layer_index is None:
        for layer in model.layers:
            layer.trainable = False
    else:
        for layer in model.layers[:num_freeze_layer_index]:
            layer.trainable = False
        for layer in model.layers[num_freeze_layer_index:]:
            layer.trainable = True


def attach_full_har_classification_head(core_model, output_shape, optimizer=tf.keras.optimizers.Adam(learning_rate=0.001), num_units=1024, model_name="HAR"):
    """
    Create a full 2-layer classification model from the base mode, using activitations from an intermediate layer with partial freezing
    Architecture:
        base_model-intermediate_layer
        -> Dense: 1024 units
        -> ReLU
        -> Dense: output_shape units
        -> Softmax
    
    Optimizer: Adam
    Loss: CategoricalCrossentropy
    Parameters:
        base_model
            the base model from which the activations are extracted
        
        output_shape
            number of output classifiction categories
        model_name
            name of the output model
        intermediate_layer
            the index of the intermediate layer from which the activations are extracted
        last_freeze_layer
            the index of the last layer to be frozen for fine-tuning (including the layer with the index)
    
    Returns:
        trainable_model (tf.keras.Model)
    """

    inputs = tf.keras.Input(shape=core_model.input.shape[1:], name='input')
    intermediate_x = core_model(inputs)

    x = tf.keras.layers.Dense(num_units, activation='relu')(intermediate_x)
    x = tf.keras.layers.Dense(output_shape)(x)
    outputs = tf.keras.layers.Softmax()(x)

    model = tf.keras.Model(inputs=inputs, outputs=outputs, name=model_name)

    model.compile(
        optimizer=optimizer,
        loss=tf.keras.losses.CategoricalCrossentropy(),
        metrics=[tf.keras.metrics.CategoricalAccuracy(name="categorical_accuracy"), tf.keras.metrics.AUC(name="auc"), tf.keras.metrics.Precision(name="precision"), tf.keras.metrics.Recall(name="recall")]
    )

    return model


def attach_linear_classification_head(core_model, output_shape, optimizer=tf.keras.optimizers.SGD(learning_rate=0.03), model_name="Linear"):

    """
    Create a linear classification model from the base mode, using activitations from an intermediate layer
    Architecture:
        base_model-intermediate_layer
        -> Dense: output_shape units
        -> Softmax
    
    Optimizer: SGD
    Loss: CategoricalCrossentropy
    Parameters:
        base_model
            the base model from which the activations are extracted
        
        output_shape
            number of output classifiction categories
        intermediate_layer
            the index of the intermediate layer from which the activations are extracted
    
    Returns:
        trainable_model (tf.keras.Model)
    """

    inputs = tf.keras.Input(shape=core_model.input.shape[1:], name='input')
    intermediate_x = core_model(inputs)

    x = tf.keras.layers.Dense(output_shape, kernel_initializer=tf.random_normal_initializer(stddev=.01))(intermediate_x)
    outputs = tf.keras.layers.Softmax()(x)

    model = tf.keras.Model(inputs=inputs, outputs=outputs, name=model_name)

    model.compile(
        optimizer=optimizer,
        loss=tf.keras.losses.CategoricalCrossentropy(),
        metrics=[tf.keras.metrics.CategoricalAccuracy(name="categorical_accuracy"), tf.keras.metrics.AUC(name="auc"), tf.keras.metrics.Precision(name="precision"), tf.keras.metrics.Recall(name="recall")]
    )
    return model


def attach_multitask_transform_head(core_model, output_tasks, optimizer, with_har_head=False, har_output_shape=None, num_units_har=1024, model_name="multitask_transform"):
    """
    Note: core_model is also modified after training this model (i.e. the weights are updated)
    """
    inputs = tf.keras.Input(shape=core_model.input.shape[1:], name='input')
    intermediate_x = core_model(inputs)
    outputs = []
    losses = [tf.keras.losses.BinaryCrossentropy() for _ in output_tasks]
    for task in output_tasks:
        x = tf.keras.layers.Dense(256, activation='relu')(intermediate_x)
        pred = tf.keras.layers.Dense(1, activation='sigmoid', name=task)(x)
        outputs.append(pred)


    if with_har_head:
        x = tf.keras.layers.Dense(num_units_har, activation='relu')(intermediate_x)
        x = tf.keras.layers.Dense(har_output_shape)(x)
        har_pred = tf.keras.layers.Softmax(name='har')(x)

        outputs.append(har_pred)
        losses.append(tf.keras.losses.CategoricalCrossentropy())

    model = tf.keras.Model(inputs=inputs, outputs=outputs, name=model_name)

    model.compile(
        optimizer=optimizer,
        loss=losses,
        metrics=['accuracy']
    )
    
    return model
