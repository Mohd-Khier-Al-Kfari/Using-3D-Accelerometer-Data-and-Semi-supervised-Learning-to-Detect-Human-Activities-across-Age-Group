import os
import gc
import pickle
import argparse
import datetime
import time
import json
import distutils.util
import pprint

import numpy as np
import tensorflow as tf
import scipy.constants
import sklearn

import data_pre_processing
import self_har_models
import self_har_utilities
import self_har_trainers
import transformations

__author__ = "C. I. Tang"
__copyright__ = "Copyright (C) 2021 C. I. Tang"

"""
Complementing the work of Tang et al.: SelfHAR: Improving Human Activity Recognition through Self-training with Unlabeled Data
@article{10.1145/3448112,
  author = {Tang, Chi Ian and Perez-Pozuelo, Ignacio and Spathis, Dimitris and Brage, Soren and Wareham, Nick and Mascolo, Cecilia},
  title = {SelfHAR: Improving Human Activity Recognition through Self-Training with Unlabeled Data},
  year = {2021},
  issue_date = {March 2021},
  publisher = {Association for Computing Machinery},
  address = {New York, NY, USA},
  volume = {5},
  number = {1},
  url = {https://doi.org/10.1145/3448112},
  doi = {10.1145/3448112},
  abstract = {Machine learning and deep learning have shown great promise in mobile sensing applications, including Human Activity Recognition. However, the performance of such models in real-world settings largely depends on the availability of large datasets that captures diverse behaviors. Recently, studies in computer vision and natural language processing have shown that leveraging massive amounts of unlabeled data enables performance on par with state-of-the-art supervised models.In this work, we present SelfHAR, a semi-supervised model that effectively learns to leverage unlabeled mobile sensing datasets to complement small labeled datasets. Our approach combines teacher-student self-training, which distills the knowledge of unlabeled and labeled datasets while allowing for data augmentation, and multi-task self-supervision, which learns robust signal-level representations by predicting distorted versions of the input.We evaluated SelfHAR on various HAR datasets and showed state-of-the-art performance over supervised and previous semi-supervised approaches, with up to 12% increase in F1 score using the same number of model parameters at inference. Furthermore, SelfHAR is data-efficient, reaching similar performance using up to 10 times less labeled data compared to supervised approaches. Our work not only achieves state-of-the-art performance in a diverse set of HAR datasets, but also sheds light on how pre-training tasks may affect downstream performance.},
  journal = {Proc. ACM Interact. Mob. Wearable Ubiquitous Technol.},
  month = mar,
  articleno = {36},
  numpages = {30},
  keywords = {semi-supervised training, human activity recognition, unlabeled data, self-supervised training, self-training, deep learning}
}

Access to Article:
    https://doi.org/10.1145/3448112
    https://dl.acm.org/doi/abs/10.1145/3448112

Contact: cit27@cl.cam.ac.uk

Copyright (C) 2021 C. I. Tang

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

"""

LOGS_SUB_DIRECTORY = 'logs'
MODELS_SUB_DIRECTORY = 'models'


def get_parser():
    def strtobool(v):
        return bool(distutils.util.strtobool(v))


    parser = argparse.ArgumentParser(
        description='SelfHAR Training')

    parser.add_argument('--working_directory', default='run',
                        help='directory containing datasets, trained models and training logs')
    parser.add_argument('--config', default='sample_configs/self_har.json',
                        help='')


    parser.add_argument('--labelled_dataset_path', default=director + label_name + ".pkl", type=str,
                        help='name of the labelled dataset for training and fine-tuning')

    parser.add_argument('--unlabelled_dataset_path', default=director + unlabel_name + ".pkl", type=str,
                        help='name of the unlabelled dataset to self-training and self-supervised training, ignored if only supervised training is performed.')
    # parser.add_argument('--window_size', default=400, type=int,
    parser.add_argument('--window_size', default=4*13, type=int, #4 second long
                        help='the size of the sliding window')
    #parser.add_argument('--max_unlabelled_windows', default=40000, type=int,
    parser.add_argument('--max_unlabelled_windows', default=4000000, type=int,
                        help='')

    parser.add_argument('--use_tensor_board_logging', default=True, type=strtobool,
                        help='')
    parser.add_argument('--verbose', default=1, type=int,
                        help='verbosity level')

    return parser

def prepare_dataset(dataset_path, window_size, get_train_test_users, validation_split_proportion=0.1, verbose=1, target=0):
    if verbose > 0:
        print(f"Loading dataset at {dataset_path}")

    with open(dataset_path, 'rb') as f:
        dataset_dict = pickle.load(f)
        user_datasets = dataset_dict['user_split']
        label_list = dataset_dict['label_list']
        label_list = np.sort(label_list)
    label_map = dict([(l, i) for i, l in enumerate(label_list)])
    output_shape = len(label_list)
    if target != 0:
        label_map = target
        output_shape = len(label_map)

    har_users = list(user_datasets.keys())
    train_users, test_users = get_train_test_users(har_users)
    if verbose > 0:
        print(f'Testing users: {test_users}, Training users: {train_users}')

    np_train, np_val, np_test = data_pre_processing.pre_process_dataset_composite(
        user_datasets=user_datasets,
        label_map=label_map,
        output_shape=output_shape,
        train_users=train_users,
        test_users=test_users,
        window_size=window_size,
        #shift=window_size//2,
        shift=window_size,
        normalise_dataset=True,
        validation_split_proportion=validation_split_proportion,
        verbose=verbose
    )

    return {
        'train': np_train,
        'val': np_val,
        'test': np_test,
        'label_map': label_map,
        'input_shape': np_train[0].shape[1:],
        'output_shape': output_shape,
    }

def generate_unlabelled_datasets_variations(unlabelled_data_x, labelled_data_x, labelled_repeat=1, verbose=1):
    if verbose > 0:
        print("Unlabeled data shape: ", unlabelled_data_x.shape)

    labelled_data_repeat = np.repeat(labelled_data_x, labelled_repeat, axis=0)
    np_unlabelled_combined = np.concatenate([unlabelled_data_x, labelled_data_repeat])
    if verbose > 0:
        print(f"Unlabelled Combined shape: {np_unlabelled_combined.shape}")
    gc.collect()

    return {
        'labelled_x_repeat': labelled_data_repeat,
        'unlabelled_combined': np_unlabelled_combined
    }

def load_unlabelled_dataset(prepared_datasets, unlabelled_dataset_path, window_size, labelled_repeat, max_unlabelled_windows=None, verbose=1):
    def get_empty_test_users(har_users):
        return (har_users, [])

    prepared_datasets['unlabelled'], label = prepare_dataset(unlabelled_dataset_path, window_size, get_empty_test_users, validation_split_proportion=0, verbose=verbose, target=prepared_datasets['labelled']['label_map'])['train']
    if max_unlabelled_windows is not None:
        prepared_datasets['unlabelled'] = prepared_datasets['unlabelled'][:max_unlabelled_windows]
    prepared_datasets = {
        **prepared_datasets,
        **generate_unlabelled_datasets_variations(
            prepared_datasets['unlabelled'],
            prepared_datasets['labelled']['train'][0],
            labelled_repeat=labelled_repeat
    )}
    return prepared_datasets, label

def get_config_default_value_if_none(experiment_config, entry, set_value=True):
    if entry in experiment_config:
        return experiment_config[entry]

    if entry == 'type':
        default_value = 'none'
    elif entry == 'tag':
        default_value = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    elif entry == 'previous_config_offset':
        default_value = 0
    elif entry == 'initial_learning_rate':
        default_value = 0.0003
    elif entry == 'epochs':
        default_value = 30
    elif entry == 'batch_size':
        #default_value = 26
        default_value = 300
    elif entry == 'optimizer':
        default_value = 'adam'
    elif entry == 'self_training_samples_per_class':
        default_value = 10000
    elif entry == 'self_training_minimum_confidence':
        default_value = 0.0
    elif entry == 'self_training_plurality_only':
        default_value = True
    elif entry == 'trained_model_path':
        default_value = ''
    elif entry == 'trained_model_type':
        default_value = 'unknown'
    elif entry == 'eval_results':
        default_value = {}
    elif entry == 'eval_har':
        default_value = False

    if set_value:
        experiment_config[entry] = default_value
        print(f"INFO: configuration {entry} set to default value: {default_value}.")

    return default_value

class Parameters:
    # constructor function
    def __init__(self, label_name, unlabel_name, percentage, director):
        self.label_name = label_name
        self.unlabel_name = unlabel_name
        self.director = director
        self.percentage = percentage

if __name__ == '__main__':

    #y = []
    #datasets_name = ["Student"]
    #datasets_name = ["University of Mannheim", "wisdm", "student dataset", "PAMAP2"]
    datasets_name = ["PAMAP2"]
    for label_datasets_name in zip(datasets_name):
        label_datasets_name = label_datasets_name[0]
        unlabel_datasets_list = ["PAMAP2", "University of Mannheim", "Student",  "wisdm", "Elderly"]
        #unlabel_datasets_list = ["PAMAP2", "Elderly"]
        unlabel_datasets_list.remove(label_datasets_name)
        for unlabel_datasets_name in zip(unlabel_datasets_list):
            unlabel_datasets_name = unlabel_datasets_name[0]
            import pandas as pd

            F1_labelled_data = pd.DataFrame(
                columns=["labelled data percentage", 'F1 Macro', 'F1 Micro', 'F1 Weighted', 'Precision', 'Recall',
                         'Kappa'],
                index=range(1, 10))
            F1_unlabelled_data = pd.DataFrame(
                columns=["labelled data percentage", 'F1 Macro', 'F1 Micro', 'F1 Weighted', 'Precision', 'Recall',
                         'Kappa'],
                index=range(1, 10))

            #for percentage in np.round(np.arange(0.1, 1, 0.1), decimals=1):
            for percentage in np.round(np.arange(0.5, 0.7, 0.1), decimals=1):
                par = Parameters(label_datasets_name, unlabel_datasets_name, percentage, "/home/mkfari/Project/SelfHAR-main/run/processed_datasets/")
                director = par.director
                label_name = par.label_name
                unlabel_name = par.unlabel_name
                percentage = par.percentage
                from sklearn.metrics import confusion_matrix

                parser = get_parser()
                args = parser.parse_args()
                tune_on_unlabelled_data = True

                with open(args.labelled_dataset_path, 'rb') as f:
                    dataset_dict = pickle.load(f)
                    datasets = dataset_dict['user_split']
                    users = list(datasets.keys())
                    
                performance_labelled_dataset = {"Experiment 2": {'Confusion Matrix': 0, 'F1 Macro': 0, 'F1 Micro': 0, 'F1 Weighted': 0, 'Precision': 0, 'Recall': 0, 'Kappa': 0},
                                                "Experiment 3": {'Confusion Matrix': 0, 'F1 Macro': 0, 'F1 Micro': 0, 'F1 Weighted': 0, 'Precision': 0, 'Recall': 0, 'Kappa': 0}}
                performance_unlabelled_dataset = {"Experiment 2": {'Confusion Matrix': 0, 'F1 Macro': 0, 'F1 Micro': 0, 'F1 Weighted': 0, 'Precision': 0, 'Recall': 0, 'Kappa': 0},
                                                "Experiment 3": {'Confusion Matrix': 0, 'F1 Macro': 0, 'F1 Micro': 0, 'F1 Weighted': 0, 'Precision': 0, 'Recall': 0, 'Kappa': 0}}

                ev = [None] * 4
                conv = [0] * 4
                y_true = [[], []]
                y_pred = [[], []]
                performance_unlabelled_dataset_dictionary = {}
                for j in range(len(users)):
                    current_time_string = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                    working_directory = args.working_directory
                    verbose = args.verbose
                    use_tensor_board_logging = args.use_tensor_board_logging
                    window_size = args.window_size

                    if use_tensor_board_logging:
                        logs_directory = os.path.join(working_directory, LOGS_SUB_DIRECTORY)
                        if not os.path.exists(logs_directory):
                            os.mkdir(logs_directory)
                    models_directory = os.path.join(working_directory, MODELS_SUB_DIRECTORY)
                    if not os.path.exists(models_directory):
                        os.mkdir(models_directory)
                    transform_funcs_vectorized = [
                        transformations.noise_transform_vectorized,
                        transformations.scaling_transform_vectorized,
                        transformations.rotation_transform_vectorized,
                        transformations.negate_transform_vectorized,
                        transformations.time_flip_transform_vectorized,
                        transformations.time_segment_permutation_transform_improved,
                        transformations.time_warp_transform_low_cost,
                        transformations.channel_shuffle_transform_vectorized
                    ]
                    transform_funcs_names = ['noised', 'scaled', 'rotated', 'negated', 'time_flipped', 'permuted', 'time_warped', 'channel_shuffled']

                    prepared_datasets = {}
                    labelled_repeat = 1             # TODO: improve flexibility transformation_multiple


                    def get_fixed_split_users(har_users):   # TODO: improve flexibility
                        test_users = har_users[j]
                        train_users = [u for u in har_users if u not in test_users]
                        return (train_users, test_users)


                    prepared_datasets['labelled'] = prepare_dataset(args.labelled_dataset_path, window_size, get_fixed_split_users, validation_split_proportion=1-percentage, verbose=verbose) #change validation set size
                    input_shape = prepared_datasets['labelled']['input_shape'] #  (window_size, 3)
                    output_shape = prepared_datasets['labelled']['output_shape']

                    with open(args.config, 'r') as f:
                        config_file = json.load(f)
                        file_tag = config_file['tag']
                        experiment_configs = config_file['experiment_configs']

                    if verbose > 0:
                        print("Experiment Settings:")
                        for i, config in enumerate(experiment_configs):
                            print(f"Experiment {i}:")
                            print(config)
                            print("------------")
                        time.sleep(5)



                    for i, experiment_config in enumerate(experiment_configs):
                        if verbose > 0:
                            print("---------------------")
                            print(f"Starting Experiment {i}: {experiment_config}")
                            print("---------------------")
                            time.sleep(5)
                        gc.collect()
                        tf.keras.backend.clear_session()



                        experiment_type = get_config_default_value_if_none(experiment_config, 'type')
                        if experiment_type == 'none':
                            continue

                        if get_config_default_value_if_none(experiment_config, 'previous_config_offset') == 0:
                            previous_config = None
                        else:
                            previous_config = experiment_configs[i - experiment_config['previous_config_offset']]
                            # if verbose > 0:
                            #     print("Previous config", previous_config)

                        tag = f"{current_time_string}_{file_tag}_{get_config_default_value_if_none(experiment_config, 'tag')}"

                        if experiment_type == 'eval_har':

                            if previous_config is None or get_config_default_value_if_none(previous_config, 'trained_model_path', set_value=False) == '':
                                print("ERROR Evaluation model does not exist")
                                continue

                            if get_config_default_value_if_none(previous_config, 'trained_model_type') == 'har_model':
                                previous_model = tf.keras.models.load_model(previous_config['trained_model_path'])
                                model = previous_model
                            elif get_config_default_value_if_none(previous_config, 'trained_model_type') == 'transform_with_har_model':
                                previous_model = tf.keras.models.load_model(previous_config['trained_model_path'])
                                model = self_har_models.extract_har_model(previous_model, optimizer=optimizer, model_name=tag)

                            pred = model.predict(prepared_datasets['labelled']['test'][0])
                            eval_results = self_har_utilities.evaluate_model_simple(pred, prepared_datasets['labelled']['test'][1])
                            if verbose > 0:
                                print(eval_results)
                            experiment_config['eval_results'] = eval_results

                            continue


                        initial_learning_rate = get_config_default_value_if_none(experiment_config, 'initial_learning_rate')
                        epochs = get_config_default_value_if_none(experiment_config, 'epochs')
                        batch_size = get_config_default_value_if_none(experiment_config, 'batch_size')
                        optimizer_type = get_config_default_value_if_none(experiment_config, 'optimizer')
                        if optimizer_type == 'adam':
                            optimizer = tf.keras.optimizers.Adam(learning_rate=initial_learning_rate)
                        elif optimizer_type == 'sgd':
                            optimizer = tf.keras.optimizers.SGD(learning_rate=initial_learning_rate)


                        if experiment_type == 'transform_train':
                            if 'unlabelled' not in prepared_datasets:
                                prepared_datasets, _ = load_unlabelled_dataset(prepared_datasets, args.unlabelled_dataset_path, window_size, labelled_repeat, max_unlabelled_windows=args.max_unlabelled_windows, verbose=verbose)

                            if previous_config is None or get_config_default_value_if_none(previous_config, 'trained_model_path', set_value=False) == '':
                                if verbose > 0:
                                    print("Creating new model...")
                                core_model = self_har_models.create_1d_conv_core_model(input_shape)
                            else:
                                if verbose > 0:
                                    print(f"Loading previous model {previous_config['trained_model_path']}")
                                previous_model = tf.keras.models.load_model(previous_config['trained_model_path'])
                                core_model = self_har_models.extract_core_model(previous_model)

                            transform_model = self_har_models.attach_multitask_transform_head(core_model, output_tasks=transform_funcs_names, optimizer=optimizer)
                            transform_model.summary()
                            if verbose > 0:
                                print(f"Dataset for transformation discrimination shape: {prepared_datasets['unlabelled_combined'].shape}")

                            multitask_transform_dataset = self_har_utilities.create_individual_transform_dataset(prepared_datasets['unlabelled_combined'], transform_funcs_vectorized)

                            multitask_transform_train = (multitask_transform_dataset[0], self_har_utilities.map_multitask_y(multitask_transform_dataset[1], transform_funcs_names))
                            multitask_split = self_har_utilities.multitask_train_test_split(multitask_transform_train, test_size=0.10, random_seed=42)
                            multitask_train = (multitask_split[0], multitask_split[1])
                            multitask_val = (multitask_split[2], multitask_split[3])


                            def training_rate_schedule(epoch):
                                rate = initial_learning_rate * (0.5 ** (epoch // 15))
                                if verbose > 0:
                                    print(f"RATE: {rate}")
                                return rate

                            training_schedule_callback = tf.keras.callbacks.LearningRateScheduler(training_rate_schedule)

                            best_transform_model_file_name, last_transform_pre_train_model_file_name = self_har_trainers.composite_train_model(
                                full_model=transform_model,
                                training_set=multitask_train,
                                validation_set=multitask_val,
                                working_directory=working_directory,
                                callbacks=[training_schedule_callback],
                                epochs=epochs,
                                batch_size=batch_size,
                                tag=tag,
                                use_tensor_board_logging=use_tensor_board_logging,
                                verbose=verbose
                            )

                            experiment_config['trained_model_path'] = best_transform_model_file_name
                            experiment_config['trained_model_type'] = 'transform_model'

                        if experiment_type == 'har_full_train' or experiment_type == 'har_full_fine_tune' or experiment_type == 'har_linear_train':

                            is_core_model = False
                            if previous_config is None or get_config_default_value_if_none(previous_config, 'trained_model_path', set_value=False) == '':
                                if verbose > 0:
                                    print("Creating new model...")
                                core_model = self_har_models.create_1d_conv_core_model(input_shape)
                                is_core_model = True
                            else:
                                if verbose > 0:
                                    print(f"Loading previous model {previous_config['trained_model_path']}")
                                previous_model = tf.keras.models.load_model(previous_config['trained_model_path'])

                                if experiment_type == 'har_linear_train':
                                    core_model = self_har_models.extract_core_model(previous_model)
                                    is_core_model = True
                                elif get_config_default_value_if_none(previous_config, 'trained_model_type') == 'har_model':
                                    har_model = previous_model
                                    is_core_model = False
                                elif previous_config['trained_model_type'] == 'transform_with_har_model':
                                    har_model = self_har_models.extract_har_model(previous_model, optimizer=optimizer, model_name=tag)
                                    is_core_model = False
                                else:
                                    core_model = self_har_models.extract_core_model(previous_model)
                                    is_core_model = True

                            if is_core_model:
                                if experiment_type == 'har_linear_train':
                                    self_har_models.set_freeze_layers(core_model, num_freeze_layer_index=None)
                                    har_model = self_har_models.attach_linear_classification_head(core_model, output_shape, optimizer=optimizer, model_name="Linear")

                                elif experiment_type == 'har_full_train':
                                    self_har_models.set_freeze_layers(core_model, num_freeze_layer_index=0)
                                    har_model = self_har_models.attach_full_har_classification_head(core_model, output_shape, optimizer=optimizer, num_units=1024, model_name="HAR")
                                elif experiment_type == 'har_full_fine_tune':
                                    self_har_models.set_freeze_layers(core_model, num_freeze_layer_index=5)
                                    har_model = self_har_models.attach_full_har_classification_head(core_model, output_shape, optimizer=optimizer, num_units=1024, model_name="HAR")
                            else:
                                if experiment_type == 'har_full_train':
                                    self_har_models.set_freeze_layers(self_har_models.extract_core_model(har_model), num_freeze_layer_index=0)
                                elif experiment_type == 'har_full_fine_tune':
                                    self_har_models.set_freeze_layers(self_har_models.extract_core_model(har_model), num_freeze_layer_index=5)

                            def training_rate_schedule(epoch):
                                rate = initial_learning_rate
                                if verbose > 0:
                                    print(f"RATE: {rate}")
                                return rate
                            training_schedule_callback = tf.keras.callbacks.LearningRateScheduler(training_rate_schedule)

                            if "Student_Fine_Tune" in tag and tune_on_unlabelled_data:
                                best_har_model_file_name, last_har_model_file_name = self_har_trainers.composite_train_model(
                                    full_model=har_model,
                                    training_set=prepared_datasets['labelled']['train'],
                                    validation_set=prepared_datasets['labelled']['val'],
                                    working_directory=working_directory,
                                    callbacks=[training_schedule_callback],
                                    epochs=epochs,
                                    batch_size=batch_size,
                                    tag=tag,
                                    use_tensor_board_logging=use_tensor_board_logging,
                                    verbose=verbose
                                )
                            else:
                                best_har_model_file_name, last_har_model_file_name = self_har_trainers.composite_train_model(
                                    full_model=har_model,
                                    training_set=prepared_datasets['labelled']['train'],
                                    validation_set=prepared_datasets['labelled']['val'],
                                    working_directory=working_directory,
                                    callbacks=[training_schedule_callback],
                                    epochs=epochs,
                                    batch_size=batch_size,
                                    tag=tag,
                                    use_tensor_board_logging=use_tensor_board_logging,
                                    verbose=verbose
                                )

                            experiment_config['trained_model_path'] = best_har_model_file_name
                            experiment_config['trained_model_type'] = 'har_model'



                        if experiment_type == 'self_training' or experiment_type == 'self_har':
                            if 'unlabelled' not in prepared_datasets:
                                prepared_datasets, _ = load_unlabelled_dataset(prepared_datasets, args.unlabelled_dataset_path, window_size, labelled_repeat, max_unlabelled_windows=args.max_unlabelled_windows)

                            if previous_config is None or get_config_default_value_if_none(previous_config, 'trained_model_path', set_value=False) == '':
                                print("ERROR No previous model for self-training")
                                break
                            else:
                                if verbose > 0:
                                    print(f"Loading previous model {previous_config['trained_model_path']}")
                                teacher_model = tf.keras.models.load_model(previous_config['trained_model_path'])
                            if verbose > 0:
                                print("Unlabelled Datasete Shape", prepared_datasets['unlabelled_combined'].shape)
                            unlabelled_pred_prob = teacher_model.predict(prepared_datasets['unlabelled_combined'], batch_size=batch_size)
                            np_self_labelled = self_har_utilities.pick_top_samples_per_class_np(
                                prepared_datasets['unlabelled_combined'],
                                unlabelled_pred_prob,
                                num_samples_per_class=get_config_default_value_if_none(experiment_config, 'self_training_samples_per_class'),
                                minimum_threshold=get_config_default_value_if_none(experiment_config, 'self_training_minimum_confidence'),
                                plurality_only=get_config_default_value_if_none(experiment_config, 'self_training_plurality_only')
                            )


                            multitask_X, multitask_transform_y, multitask_har_y = self_har_utilities.create_individual_transform_dataset(
                                np_self_labelled[0],
                                transform_funcs_vectorized,
                                other_labels=np_self_labelled[1]
                            )


                            core_model = self_har_models.create_1d_conv_core_model(input_shape)
                            def training_rate_schedule(epoch):
                                rate = 0.0003 * (0.5 ** (epoch // 15))
                                if verbose > 0:
                                    print(f"RATE: {rate}")
                                return rate
                            training_schedule_callback = tf.keras.callbacks.LearningRateScheduler(training_rate_schedule)


                            if experiment_type == 'self_training':
                                student_pre_train_dataset = np_self_labelled

                                student_model = self_har_models.attach_full_har_classification_head(core_model, output_shape, optimizer=optimizer, model_name="StudentPreTrain")
                                student_model.summary()

                                pre_train_split = sklearn.model_selection.train_test_split(student_pre_train_dataset[0], student_pre_train_dataset[1], test_size=0.10, random_state=42)
                                student_pre_train_split_train = (pre_train_split[0], pre_train_split[2])
                                student_pre_train_split_val = (pre_train_split[1], pre_train_split[3])

                            else:

                                multitask_transform_y_mapped = self_har_utilities.map_multitask_y(multitask_transform_y, transform_funcs_names)
                                multitask_transform_y_mapped['har'] = multitask_har_y
                                self_har_train = (multitask_X, multitask_transform_y_mapped)
                                student_pre_train_dataset = self_har_train\

                                student_model = self_har_models.attach_multitask_transform_head(core_model, output_tasks=transform_funcs_names, optimizer=optimizer, with_har_head=True, har_output_shape=output_shape, num_units_har=1024, model_name="StudentPreTrain")
                                student_model.summary()

                                pre_train_split = self_har_utilities.multitask_train_test_split(student_pre_train_dataset, test_size=0.10, random_seed=42)

                                student_pre_train_split_train = (pre_train_split[0], pre_train_split[1])
                                student_pre_train_split_val = (pre_train_split[2], pre_train_split[3])


                            best_student_pre_train_file_name, last_student_pre_train_file_name = self_har_trainers.composite_train_model(
                                full_model=student_model,
                                training_set=student_pre_train_split_train,
                                validation_set=student_pre_train_split_val,
                                working_directory=working_directory,
                                callbacks=[training_schedule_callback],
                                epochs=epochs,
                                batch_size=batch_size,
                                tag=tag,
                                use_tensor_board_logging=use_tensor_board_logging,
                                verbose=verbose
                            )


                            experiment_config['trained_model_path'] = best_student_pre_train_file_name
                            if experiment_type == 'self_training':
                                experiment_config['trained_model_type'] = 'har_model'
                            else:
                                experiment_config['trained_model_type'] = 'transform_with_har_model'


                        if get_config_default_value_if_none(experiment_config, 'eval_har', set_value=False):
                            if get_config_default_value_if_none(experiment_config, 'trained_model_type') == 'har_model':
                                best_har_model = tf.keras.models.load_model(experiment_config['trained_model_path'])
                            elif get_config_default_value_if_none(experiment_config, 'trained_model_type') == 'transform_with_har_model':
                                previous_model = tf.keras.models.load_model(experiment_config['trained_model_path'])
                                best_har_model = self_har_models.extract_har_model(previous_model, optimizer=optimizer, model_name=tag)
                            else:
                                continue

                            pred = best_har_model.predict(prepared_datasets['labelled']['test'][0])
                            eval_results = self_har_utilities.evaluate_model_simple(pred, prepared_datasets['labelled']['test'][1])

                            "label the un labelled dataset"
                            #if (i == 3 and label_datasets_name == "University of Mannheim") or (i == 2 and label_datasets_name == "PAMAP2"):
                            if (i == 3 and percentage == 0.5):
                                import pandas as pd
                                gc.collect()
                                DF = pd.read_csv(f"/home/mkfari/Project/datasets csv after clustering/{unlabel_datasets_name}.csv")
                                DF_acc = (DF[["acc_x", "acc_y", "acc_z"]] - np.array(
                                    np.mean(DF[["acc_x", "acc_y", "acc_z"]]))) / np.array(
                                    np.std(DF[["acc_x", "acc_y", "acc_z"]]))
                                DF_acc = DF_acc.to_numpy()
                                DF_acc = np.reshape(DF_acc[0: int(np.shape(DF_acc)[0] / window_size) * window_size],
                                                        (-1, window_size, np.shape(DF_acc)[1]))
                                label_array = DF["label"].to_numpy()
                                label_array = np.reshape(label_array[0: int(np.shape(label_array)[0] / window_size) * window_size], (-1, window_size,))
                                label_array = label_array[:, window_size - 1]
                                CLASS = best_har_model.predict(DF_acc)

                                from sklearn.preprocessing import LabelEncoder

                                lab = LabelEncoder()
                                lab.fit(list(prepared_datasets["labelled"]['label_map'].keys()))
                                enc = lab.transform(label_array).astype(int)
                                enc = enc.reshape(len(enc), 1)
                                #from sklearn.preprocessing import OneHotEncoder
                                #OneH = OneHotEncoder()
                                #enc = OneH.fit_transform(enc).toarray()
                                #EV = self_har_utilities.evaluate_model_simple(enc, CLASS)
                                #print(EV)
                                CLASS = np.argmax(CLASS, axis=1)
                                CLASS = lab.inverse_transform(CLASS)
                                label_array = label_array.reshape(len(label_array), 1)
                                CLASS = CLASS.reshape(len(CLASS), 1)

                                import sys
                                sys.path.insert(0, '/home/mkfari/Project/Labeled dataset/decompressed/Code/Clustering')
                                from Clustering_algorithm import Labeling

                                if unlabel_datasets_name == "Elderly":
                                    for L in range(1, 11):
                                        print(f"L = {L}")
                                        DF1 = Labeling(window_size, CLASS[int(len(CLASS) * (L-1) / 10):int(len(CLASS) * L / 10)],
                                                       DF[int(len(CLASS) * (L-1) / 10) * window_size:int(len(CLASS) * L / 10) * window_size].reset_index(drop=True), "SelfHAR")
                                        isExist = os.path.exists(f"/home/mkfari/Project/datasets csv after clustering/After SelfHAR {label_datasets_name}")
                                        if not isExist:
                                            os.makedirs(f"/home/mkfari/Project/datasets csv after clustering/After SelfHAR {label_datasets_name}")
                                            print("The new directory is created!")

                                        DF1.to_csv(f"/home/mkfari/Project/datasets csv after clustering/After SelfHAR {label_datasets_name}/{unlabel_datasets_name}_{L}.csv", index=False)
                                        gc.collect()

                                else:
                                    DF = Labeling(window_size, CLASS, DF, "SelfHAR")

                                    isExist = os.path.exists(f"/home/mkfari/Project/datasets csv after clustering/After SelfHAR {label_datasets_name}")
                                    if not isExist:
                                        os.makedirs(f"/home/mkfari/Project/datasets csv after clustering/After SelfHAR {label_datasets_name}")
                                        print("The new directory is created!")

                                    DF.to_csv(f"/home/mkfari/Project/datasets csv after clustering/After SelfHAR {label_datasets_name}/{unlabel_datasets_name}.csv", index=False)
                                    gc.collect()
                                    DF = pd.DataFrame()

                            if i == 2:

                                data, label = load_unlabelled_dataset(prepared_datasets, args.unlabelled_dataset_path, window_size,
                                                                      labelled_repeat,
                                                                      max_unlabelled_windows=args.max_unlabelled_windows,
                                                                      verbose=verbose)
                                classes = best_har_model.predict(data['unlabelled'])
            
                                ev[i] = self_har_utilities.evaluate_model_simple(classes, label)
                                print(eval_results)
                                conv[i] = conv[i] + ev[i]['Confusion Matrix']
                                y_true[i - 2] = y_true[i - 2] + np.argmax(prepared_datasets['labelled']['test'][1], axis=1).tolist()
                                y_pred[i - 2] = y_pred[i - 2] + np.argmax(pred, axis=1).tolist()
                                from glob import glob
                                #classes = np.argmax(pred, axis=1)

                                #labeledfolder = '/home/mkfari/Project/Labeled dataset/decompressed/Labeled Data'
                                #labeledfolder = "/home/mkfari/Project/Labeled dataset/decompressed/Code/Clustering/clustered data/2 stage 6 clusters"
                                #datasetFiles = sorted(glob(labeledfolder + "/*.csv"))  # Read names of dataset folders
                                #matching = [s for s in datasetFiles if users[j] in s]
                                #w = 0
                                """
                                for m in matching:
                                    data = pd.read_csv(m).drop(['Unnamed: 0'], axis=1)
                                    data.columns = ["time", "acc_x", "acc_y", "acc_z", "label"]
                                    #data = pd.read_csv(m)
                                    #data.columns = ["time", "acc_x", "acc_y", "acc_z", "label", "cluster", "cluster label"]
                                    data['class'] = "Nan"
                                    # data.insert(loc=5, column="class", value=0)
                                    step = 200
                                    data.loc[0:100, "class"] = classes[w]
                                    for q in range(100, len(data) - step - 100, step):
                                        data.loc[q:q + step, "class"] = classes[w]
                                        w = w + 1
            
                                    data.loc[q + step:len(data) - 1, "class"] = classes[w - 1]
            
                                    data.loc[data['class'] == 0, "class"] = 'laying'
                                    data.loc[data['class'] == 1, "class"] = 'sitting'
                                    data.loc[data['class'] == 2, "class"] = 'walking'
                                    data.loc[data['class'] == 3, "class"] = 'running'
            
                                    data.to_csv("/home/mkfari/Project/SelfHAR-main/classifiers" + m.replace(labeledfolder, ""), index=False)
                                """
                            if i == 3:
                                data, label = load_unlabelled_dataset(prepared_datasets, args.unlabelled_dataset_path,
                                                                      window_size,
                                                                      labelled_repeat,
                                                                      max_unlabelled_windows=args.max_unlabelled_windows,
                                                                      verbose=verbose)
                                classes = best_har_model.predict(data['unlabelled'])

                                ev[i] = self_har_utilities.evaluate_model_simple(classes, label)
                                conv[i] = conv[i] + ev[i]['Confusion Matrix']
                                y_true[i - 2] = y_true[i - 2] + np.argmax(prepared_datasets['labelled']['test'][1], axis=1).tolist()
                                y_pred[i - 2] = y_pred[i - 2] + np.argmax(pred, axis=1).tolist()

                            #best_har_model.save('/home/mkfari/Project/SelfHAR-main/classifiers/' + users[j] + "_Experiment_" + str(i) + ".h5")                eval_results = self_har_utilities.evaluate_model_simple(pred, prepared_datasets['labelled']['test'][1])
                            #eval_results = self_har_utilities.evaluate_model_simple(pred, prepared_datasets['labelled']['test'][1])
                            if verbose > 0:
                                print(eval_results)
                            experiment_config['eval_results'] = eval_results
                            #x = [prepared_datasets['labelled']['test'][0], np.argmax(pred, axis=1)]
                            #y.append(x)

                    if verbose > 0:
                        print(f"unlabeled dataset performance per fold {ev}")

                        print("Finshed running all experiments.")
                        print("Summary:")
                        for i, config in enumerate(experiment_configs):
                            print(f"Experiment {i}:")
                            print(config)
                            print("------------")
                            performance_unlabelled_dataset_dictionary[j] = ev.copy()
                            if i == 2 or i == 3:
                            #if i == 2:

                                for k in performance_labelled_dataset[f"Experiment {i}"]:
                                    if k == 'Confusion Matrix':
                                        continue
                                    performance_labelled_dataset[f"Experiment {i}"][k] = performance_labelled_dataset[f"Experiment {i}"][k] + config['eval_results'][k]
                                    performance_unlabelled_dataset[f"Experiment {i}"][k] = performance_unlabelled_dataset[f"Experiment {i}"][k] + ev[i][k]

                        path = f"/home/mkfari/Project/SelfHAR-main/classifiers/{label_name}/{unlabel_name}/ labelled data percentage {percentage}"
                        isExist = os.path.exists(path)
                        if not isExist:
                            os.makedirs(path)
                            print("The new directory is created!")
                        with open(f'{path}/experiment_configs {users[j]}.txt', 'w') as f:
                            f.write(str(experiment_configs))


                    result_summary_path = os.path.join(working_directory, f"{current_time_string}_{file_tag}_results_summary.txt")
                    with open(result_summary_path, 'w') as f:
                        structured = pprint.pformat(experiment_configs, indent=4)
                        f.write(structured)
                    if verbose > 0:
                        print("Saved results summary to ", result_summary_path)

                for k in performance_labelled_dataset["Experiment 2"]:
                    if k == 'Confusion Matrix':
                        continue
                    performance_labelled_dataset["Experiment 2"][k] = performance_labelled_dataset["Experiment 2"][k] / len(users)
                    performance_labelled_dataset["Experiment 3"][k] = performance_labelled_dataset["Experiment 3"][k] / len(users)

                    performance_unlabelled_dataset["Experiment 2"][k] = performance_unlabelled_dataset["Experiment 2"][k] / len(users)
                    performance_unlabelled_dataset["Experiment 3"][k] = performance_unlabelled_dataset["Experiment 3"][k] / len(users)

                performance_unlabelled_dataset[f"Experiment {2}"]['Confusion Matrix'] = conv[2] / len(users)
                performance_unlabelled_dataset[f"Experiment {3}"]['Confusion Matrix'] = conv[3] / len(users)

                performance_labelled_dataset[f"Experiment {2}"]['Confusion Matrix'] = confusion_matrix(y_true[0], y_pred[0])
                performance_labelled_dataset[f"Experiment {3}"]['Confusion Matrix'] = confusion_matrix(y_true[1], y_pred[1])
                with open(f'{path}/performance_labelled_dataset.txt', 'w') as f:
                    f.write(str(performance_labelled_dataset))

                with open(f'{path}/performance_unlabelled_dataset.txt', 'w') as f:
                    f.write(str(performance_unlabelled_dataset))

                with open(f'{path}/performance_unlabelled_dataset_dictionary.txt', 'w') as f:
                    f.write(str(performance_unlabelled_dataset_dictionary))


                print(performance_labelled_dataset)
                print(performance_unlabelled_dataset)


                F1_labelled_data['labelled data percentage'][int(percentage * 10)] = percentage
                F1_unlabelled_data['labelled data percentage'][int(percentage * 10)] = percentage

                for columns in F1_labelled_data.columns[F1_labelled_data.columns !='labelled data percentage']:
                    F1_labelled_data[columns][int(percentage * 10)] = performance_labelled_dataset["Experiment 2"][columns]
                    F1_unlabelled_data[columns][int(percentage * 10)] = performance_unlabelled_dataset["Experiment 2"][columns]

            F1_labelled_data.to_csv(
                f"/home/mkfari/Project/SelfHAR-main/classifiers/{label_name}/{unlabel_name}/ F1_labelled_data.csv",
                index=False)

            F1_unlabelled_data.to_csv(
                f"/home/mkfari/Project/SelfHAR-main/classifiers/{label_name}/{unlabel_name}/ F1_unlabelled_data.csv",
                index=False)