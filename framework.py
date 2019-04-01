#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# Author: kerlomz <kerlomz@gmail.com>
import sys
import warpctc_tensorflow
import tensorflow as tf
from tensorflow.python.training import moving_averages
from config import *
from SRU import SRUCell


class GraphOCR(object):

    def __init__(self, mode, cnn: CNNNetwork, recurrent: RecurrentNetwork):
        self.mode = mode
        self.network = cnn
        self.recurrent = recurrent
        self.inputs = tf.placeholder(tf.float32, [None, RESIZE[0], RESIZE[1], 1], name='input')
        # self.labels = tf.sparse_placeholder(tf.int32, name='labels')
        self.labels = tf.placeholder(tf.int32, [None])
        self.label_len = tf.placeholder(tf.int32, [None])
        self._extra_train_ops = []
        self.seq_len = None
        self.merged_summary = None
        self.last_batch_error = None

    def build_graph(self):
        self._build_model()
        self._build_train_op()
        self.merged_summary = tf.summary.merge_all()

    def _build_model(self):
        if self.network == CNNNetwork.CNN5:
            filters = [32, 64, 128, 128, 64]
            strides = [1, 2]

            with tf.variable_scope('cnn'):
                with tf.variable_scope('unit-1'):
                    x = self._conv2d(self.inputs, 'cnn-1', 7, 1, filters[0], strides[0])
                    x = self._batch_norm('bn1', x)
                    x = self._leaky_relu(x, 0.01)
                    x = self._max_pool(x, 2, strides[0])

                with tf.variable_scope('unit-2'):
                    x = self._conv2d(x, 'cnn-2', 5, filters[0], filters[1], strides[0])
                    x = self._batch_norm('bn2', x)
                    x = self._leaky_relu(x, 0.01)
                    x = self._max_pool(x, 2, strides[1])

                with tf.variable_scope('unit-3'):
                    x = self._conv2d(x, 'cnn-3', 3, filters[1], filters[2], strides[0])
                    x = self._batch_norm('bn3', x)
                    x = self._leaky_relu(x, 0.01)
                    x = self._max_pool(x, 2, strides[1])

                with tf.variable_scope('unit-4'):
                    x = self._conv2d(x, 'cnn-4', 3, filters[2], filters[3], strides[0])
                    x = self._batch_norm('bn4', x)
                    x = self._leaky_relu(x, 0.01)
                    x = self._max_pool(x, 2, strides[1])

                with tf.variable_scope('unit-5'):
                    x = self._conv2d(x, 'cnn-5', 3, filters[3], filters[4], strides[0])
                    x = self._batch_norm('bn5', x)
                    x = self._leaky_relu(x, 0.01)
                    x = self._max_pool(x, 2, strides[1])

        elif self.network == CNNNetwork.ResNet:

            x = self.zero_padding(self.inputs, (3, 3))

            # Stage 1
            _, _, _, in_channels = x.shape.as_list()

            a1 = self._conv2d(
                x=x,
                name="conv1",
                filter_size=7,
                in_channels=in_channels,
                out_channels=64,
                strides=2,
                padding='VALID'
            )

            a1 = self._batch_norm(x=a1, name='bn_conv1')
            a1 = tf.nn.relu(a1)
            # a1 = self._leaky_relu(a1)

            a1 = tf.nn.max_pool(a1, ksize=(1, 3, 3, 1), strides=(1, 2, 2, 1), padding='VALID')

            # Stage 2
            a2 = self.convolutional_block(a1, f=3, out_channels=[64, 64, 256], stage=2, block='a', s=1)
            a2 = self.identity_block(a2, f=3, out_channels=[64, 64, 256], stage=2, block='b')
            a2 = self.identity_block(a2, f=3, out_channels=[64, 64, 256], stage=2, block='c')

            # Stage 3
            a3 = self.convolutional_block(a2, 3, [128, 128, 512], stage=3, block='a', s=2)
            a3 = self.identity_block(a3, 3, [128, 128, 512], stage=3, block='b')
            a3 = self.identity_block(a3, 3, [128, 128, 512], stage=3, block='c')
            a3 = self.identity_block(a3, 3, [128, 128, 512], stage=3, block='d')

            # Stage 4
            a4 = self.convolutional_block(a3, 3, [256, 256, 1024], stage=4, block='a', s=2)
            a4 = self.identity_block(a4, 3, [256, 256, 1024], stage=4, block='b')
            a4 = self.identity_block(a4, 3, [256, 256, 1024], stage=4, block='c')
            a4 = self.identity_block(a4, 3, [256, 256, 1024], stage=4, block='d')
            a4 = self.identity_block(a4, 3, [256, 256, 1024], stage=4, block='e')
            a4 = self.identity_block(a4, 3, [256, 256, 1024], stage=4, block='f')

            # Stage 5
            a5 = self.convolutional_block(a4, 3, [512, 512, 2048], stage=5, block='a', s=2)
            a5 = self.identity_block(a5, 3, [512, 512, 2048], stage=5, block='b')
            x = self.identity_block(a5, 3, [512, 512, 2048], stage=5, block='c')
            # x = tf.nn.avg_pool(x, ksize=(1, 2, 2, 1), strides=(1, 2, 2, 1), padding='VALID', name='avg_pool')

        elif self.network == CNNNetwork.DenseNet:
            with tf.variable_scope('DenseNet'):
                nb_filter = 64
                x = tf.layers.conv2d(
                    self.inputs,
                    filters=nb_filter,
                    kernel_size=5,
                    strides=(2, 2),
                    padding="SAME",
                    use_bias=False
                )
                x, nb_filter = self._dense_block(x, 8, 8, nb_filter)
                x, nb_filter = self._transition_block(x, 128, pool_type=2)
                x, nb_filter = self._dense_block(x, 8, 8, nb_filter)
                x, nb_filter = self._transition_block(x, 128, pool_type=3)
                x, nb_filter = self._dense_block(x, 8, 8, nb_filter)
        else:
            print('This cnn neural network is not supported at this time.')
            sys.exit(-1)

        shape_list = x.get_shape().as_list()
        # batch_size, time_steps = tf.shape(x)[0], tf.shape(x)[1]
        if self.network == CNNNetwork.ResNet:
            x = tf.reshape(x, [-1, shape_list[1] * shape_list[2], shape_list[3]])
        else:
            x = tf.reshape(x, [-1, shape_list[1], shape_list[2] * shape_list[3]])
        shape_list = x.get_shape().as_list()
        self.seq_len = tf.fill([tf.shape(x)[0]], shape_list[1], name="seq_len")
        if self.recurrent == RecurrentNetwork.LSTM:
            with tf.variable_scope('LSTM'):
                cell1 = tf.contrib.rnn.LSTMCell(NUM_HIDDEN * 2, state_is_tuple=True)
                if self.mode == RunMode.Trains:
                    cell1 = tf.contrib.rnn.DropoutWrapper(cell=cell1, output_keep_prob=0.8)
                cell2 = tf.contrib.rnn.LSTMCell(NUM_HIDDEN * 2, state_is_tuple=True)
                if self.mode == RunMode.Trains:
                    cell2 = tf.contrib.rnn.DropoutWrapper(cell=cell2, output_keep_prob=0.8)

                stack = tf.contrib.rnn.MultiRNNCell([cell1, cell2], state_is_tuple=True)
                outputs, _ = tf.nn.dynamic_rnn(stack, x, self.seq_len, dtype=tf.float32)

        elif self.recurrent == RecurrentNetwork.BLSTM:
            with tf.variable_scope('BLSTM'):

                outputs = self._stacked_bidirectional_rnn(
                    tf.contrib.rnn.LSTMCell,
                    NUM_HIDDEN,
                    LSTM_LAYER_NUM,
                    x,
                    self.seq_len
                )
        elif self.recurrent == RecurrentNetwork.SRU:
            cell1 = SRUCell(NUM_HIDDEN * 2, False)
            cell2 = SRUCell(NUM_HIDDEN * 2, False)

            stack = tf.contrib.rnn.MultiRNNCell([cell1, cell2], state_is_tuple=True)
            outputs, _ = tf.nn.dynamic_rnn(stack, x, self.seq_len, dtype=tf.float32)

        elif self.recurrent == RecurrentNetwork.BSRU:
            with tf.variable_scope('BSRU'):

                outputs = self._stacked_bidirectional_rnn(
                    SRUCell,
                    NUM_HIDDEN,
                    LSTM_LAYER_NUM,
                    x,
                    self.seq_len
                )
        else:
            print('This recurrent neural network is not supported at this time.')
            sys.exit(-1)

        # Reshaping to apply the same weights over the time_steps
        outputs = tf.reshape(outputs, [-1, NUM_HIDDEN * 2])
        with tf.variable_scope('output'):
            # tf.Variable
            weight_out = tf.get_variable(
                name='weight',
                shape=[outputs.get_shape()[1] if self.network == CNNNetwork.ResNet else NUM_HIDDEN * 2, NUM_CLASSES],
                dtype=tf.float32,
                initializer=tf.truncated_normal_initializer(stddev=0.1),
                # initializer=tf.glorot_uniform_initializer(),
                # initializer=tf.contrib.layers.xavier_initializer(),
                # initializer=tf.truncated_normal([NUM_HIDDEN, NUM_CLASSES], stddev=0.1),
            )
            biases_out = tf.get_variable(
                name='biases',
                shape=[NUM_CLASSES],
                dtype=tf.float32,
                initializer=tf.constant_initializer(value=0, dtype=tf.float32)
            )
            # [batch_size * max_timesteps, num_classes]
            logits = tf.matmul(outputs, weight_out) + biases_out
            # Reshaping back to the original shape
            logits = tf.reshape(logits, [tf.shape(x)[0], -1, NUM_CLASSES])
            # Time major
            predict = tf.transpose(logits, (1, 0, 2), "predict")
            self.predict = predict

    def _build_train_op(self):
        self.global_step = tf.train.get_or_create_global_step()
        # ctc loss function, using forward and backward algorithms and maximum likelihood.

        # with tf.get_default_graph()._kernel_label_map({"CTCLoss": "WarpCTC"}):
        #     self.loss = tf.nn.ctc_loss(inputs=self.predict, labels=self.labels, sequence_length=self.seq_len)

        self.loss = warpctc_tensorflow.ctc(
            activations=self.predict,
            flat_labels=self.labels,
            label_lengths=self.label_len,
            input_lengths=self.seq_len
        )

        self.cost = tf.reduce_mean(self.loss)
        tf.summary.scalar('cost', self.cost)

        self.lrn_rate = tf.train.exponential_decay(
            TRAINS_LEARNING_RATE,
            self.global_step,
            DECAY_STEPS,
            DECAY_RATE,
            staircase=True
        )
        tf.summary.scalar('learning_rate', self.lrn_rate)

        self.optimizer = tf.train.MomentumOptimizer(
            learning_rate=self.lrn_rate,
            use_nesterov=True,
            momentum=MOMENTUM,
        ).minimize(
            self.cost,
            global_step=self.global_step
        )

        # Storing adjusted smoothed mean and smoothed variance operations
        train_ops = [self.optimizer] + self._extra_train_ops
        self.train_op = tf.group(*train_ops)

        # Option 2: tf.contrib.ctc.ctc_beam_search_decoder
        # (it's slower but you'll get better results)
        self.decoded, self.log_prob = tf.nn.ctc_greedy_decoder(
            self.predict,
            self.seq_len,
            merge_repeated=False
        )

        # Find the optimal path
        # self.decoded, self.log_prob = tf.nn.ctc_beam_search_decoder(
        #     self.predict,
        #     self.seq_len,
        #     merge_repeated=False,
        # )

        self.dense_decoded = tf.sparse_tensor_to_dense(self.decoded[0], default_value=-1, name="dense_decoded")

        # self.last_batch_error = tf.reduce_mean(tf.edit_distance(tf.cast(self.decoded[0], tf.int32), self.labels))

    def zero_padding(self, x, pad=(3, 3)):
        padding = tf.constant([[0, 0], [pad[0], pad[0]], [pad[1], pad[1]], [0, 0]])
        return tf.pad(x, padding, 'CONSTANT')

    # def _batch_norm(self, name, x):
    #     with tf.variable_scope(name):
    #
    #         # Get the last dimension of tensor, the mean after, the variance is this dimension
    #         params_shape = [x.get_shape()[-1]]
    #
    #         # Normalized data is the mean value of 0 after the variance is 1,
    #         # - there is also an adjustment of x = x * gamma + beta
    #         # This will continue to adjust with training
    #         beta = tf.get_variable(
    #             'beta', params_shape, tf.float32,
    #             initializer=tf.constant_initializer(0.0, tf.float32))
    #         gamma = tf.get_variable(
    #             'gamma', params_shape, tf.float32,
    #             initializer=tf.constant_initializer(1.0, tf.float32))
    #
    #         # When training, constantly adjust the smoothing mean, smoothing the variance
    #         # In the prediction process, the adjusted smooth variance mean is used for standardization during training.
    #         if self.mode == RunMode.Trains:
    #             # Get batch average and variance, size[Last Dimension]
    #             mean, variance = tf.nn.moments(x, [0, 1, 2], name='moments')
    #
    #             # These two names, moving_mean and moving_variance must be equal to both training and prediction
    #             # - get_variable() can be used to create shared variables
    #             moving_mean = tf.get_variable(
    #                 'moving_mean', params_shape, tf.float32,
    #                 initializer=tf.constant_initializer(0.0, tf.float32),
    #                 trainable=False)
    #             moving_variance = tf.get_variable(
    #                 'moving_variance', params_shape, tf.float32,
    #                 initializer=tf.constant_initializer(1.0, tf.float32),
    #                 trainable=False)
    #
    #             self._extra_train_ops.append(moving_averages.assign_moving_average(
    #                 moving_mean, mean, 0.9))
    #             self._extra_train_ops.append(moving_averages.assign_moving_average(
    #                 moving_variance, variance, 0.9))
    #         else:
    #             mean = tf.get_variable(
    #                 'moving_mean', params_shape, tf.float32,
    #                 initializer=tf.constant_initializer(0.0, tf.float32),
    #                 trainable=False)
    #             variance = tf.get_variable(
    #                 'moving_variance', params_shape, tf.float32,
    #                 initializer=tf.constant_initializer(1.0, tf.float32),
    #                 trainable=False)
    #
    #             tf.summary.histogram(mean.op.name, mean)
    #             tf.summary.histogram(variance.op.name, variance)
    #
    #         x_bn = tf.nn.batch_normalization(x, mean, variance, beta, gamma, 0.001)
    #         x_bn.set_shape(x.get_shape())
    #
    #         return x_bn

    def _conv2d(self, x, name, filter_size, in_channels, out_channels, strides, padding='SAME'):
        # n = filter_size * filter_size * out_channels
        with tf.variable_scope(name):
            kernel = tf.get_variable(name='DW',
                                     shape=[filter_size, filter_size, in_channels, out_channels],
                                     dtype=tf.float32,
                                     initializer=tf.contrib.layers.xavier_initializer()
                                     # initializer=tf.random_normal_initializer(stddev=np.sqrt(2.0 / n))
                                     )

            b = tf.get_variable(name='bais',
                                shape=[out_channels],
                                dtype=tf.float32,
                                initializer=tf.constant_initializer())
            con2d_op = tf.nn.conv2d(x, kernel, [1, strides, strides, 1], padding=padding)
        # return con2d_op
        return tf.nn.bias_add(con2d_op, b)

    def identity_block(self, x, f, out_channels, stage, block):
        """
        Implementing a ResNet identity block with shortcut path
        passing over 3 Conv Layers

        @params
        X - input tensor of shape (m, in_H, in_W, in_C)
        f - size of middle layer filter
        out_channels - tuple of number of filters in 3 layers
        stage - used to name the layers
        block - used to name the layers

        @returns
        A - Output of identity_block
        params - Params used in identity block
        """

        conv_name = 'res' + str(stage) + block + '_branch'
        bn_name = 'bn' + str(stage) + block + '_branch'

        input_tensor = x

        _, _, _, in_channels = x.shape.as_list()

        x = self._conv2d(
            x=x,
            name="{}2a".format(conv_name),
            filter_size=1,
            in_channels=in_channels,
            out_channels=out_channels[0],
            strides=1,
            padding='VALID'
        )

        x = self._batch_norm(x=x, name=bn_name + '2a')
        # x = tf.nn.relu(x)
        x = self._leaky_relu(x)

        _, _, _, in_channels = x.shape.as_list()
        x = self._conv2d(
            x=x,
            name="{}2b".format(conv_name),
            filter_size=f,
            in_channels=in_channels,
            out_channels=out_channels[1],
            strides=1,
            padding='SAME'
        )
        x = self._batch_norm(x=x, name=bn_name + '2b')
        # x = tf.nn.relu(x)
        x = self._leaky_relu(x)

        _, _, _, in_channels = x.shape.as_list()
        x = self._conv2d(
            x=x,
            name="{}2c".format(conv_name),
            filter_size=1,
            in_channels=in_channels,
            out_channels=out_channels[2],
            strides=1,
            padding='VALID'
        )
        x = self._batch_norm(x=x, name=bn_name + '2c')

        x = tf.add(input_tensor, x)
        # x = tf.nn.relu(x)
        x = self._leaky_relu(x)

        return x

    def convolutional_block(self, x, f, out_channels, stage, block, s=2):
        """
        Implementing a ResNet convolutional block with shortcut path
        passing over 3 Conv Layers having different sizes

        @params
        X - input tensor of shape (m, in_H, in_W, in_C)
        f - size of middle layer filter
        out_channels - tuple of number of filters in 3 layers
        stage - used to name the layers
        block - used to name the layers
        s - strides used in first layer of convolutional block

        @returns
        A - Output of convolutional_block
        params - Params used in convolutional block
        """

        conv_name = 'res' + str(stage) + block + '_branch'
        bn_name = 'bn' + str(stage) + block + '_branch'

        _, _, _, in_channels = x.shape.as_list()
        a1 = self._conv2d(
            x=x,
            name="{}2a".format(conv_name),
            filter_size=1,
            in_channels=in_channels,
            out_channels=out_channels[0],
            strides=s,
            padding='VALID'
        )
        a1 = self._batch_norm(x=a1, name=bn_name + '2a')
        # a1 = tf.nn.relu(a1)
        a1 = self._leaky_relu(a1)

        _, _, _, in_channels = a1.shape.as_list()
        a2 = self._conv2d(
            x=a1,
            name="{}2b".format(conv_name),
            filter_size=f,
            in_channels=in_channels,
            out_channels=out_channels[1],
            strides=1,
            padding='SAME'
        )
        a2 = self._batch_norm(x=a2, name=bn_name + '2b')
        # a2 = tf.nn.relu(a2)
        a2 = self._leaky_relu(a2)

        _, _, _, in_channels = a2.shape.as_list()
        a3 = self._conv2d(
            x=a2,
            name="{}2c".format(conv_name),
            filter_size=1,
            in_channels=in_channels,
            out_channels=out_channels[2],
            strides=1,
            padding='VALID'
        )
        a3 = self._batch_norm(x=a3, name=bn_name + '2c')
        # a3 = tf.nn.relu(a3)
        a3 = self._leaky_relu(a3)

        _, _, _, in_channels = x.shape.as_list()
        x = self._conv2d(
            x=x,
            name="{}1".format(conv_name),
            filter_size=1,
            in_channels=in_channels,
            out_channels=out_channels[2],
            strides=s,
            padding='VALID'
        )

        x = self._batch_norm(x=x, name=bn_name + '1')

        x = tf.add(a3, x)
        x = self._leaky_relu(x)
        # x = tf.nn.relu(x)

        return x

    # Variant Relu
    # The gradient of the non-negative interval is constant,
    # - which can prevent the gradient from disappearing to some extent.
    @staticmethod
    def _leaky_relu(x, leakiness=0.0):
        return tf.where(tf.less(x, 0.0), leakiness * x, x, name='leaky_relu')

    @staticmethod
    def _max_pool(x, ksize, strides):
        return tf.nn.max_pool(
            x,
            ksize=[1, ksize, ksize, 1],
            strides=[1, strides, strides, 1],
            padding='SAME',
            name='max_pool'
        )

    def _conv_block(self, x, growth_rate, dropout_rate=None):
        _x = tf.layers.batch_normalization(x, training=True)
        # _x = tf.nn.relu(_x)
        _x = self._leaky_relu(_x)

        _x = tf.layers.conv2d(_x, growth_rate, 3, 1, 'SAME')
        if dropout_rate is not None:
            _x = tf.nn.dropout(_x, dropout_rate)
        return _x

    def _dense_block(self, x, nb_layers, growth_rate, nb_filter, dropout_rate=0.2):
        for i in range(nb_layers):
            cb = self._conv_block(x, growth_rate, dropout_rate)
            x = tf.concat([x, cb], 3)
            nb_filter += growth_rate
        return x, nb_filter

    def _transition_block(self, x, filters, dropout_kp=None, pool_type=1):
        _x = tf.layers.batch_normalization(x, training=True)
        _x = tf.nn.relu(_x)
        _x = tf.layers.conv2d(_x, filters=filters, kernel_size=1, strides=(1, 1), padding="SAME")
        if dropout_kp is not None:
            _x = tf.nn.dropout(_x, dropout_kp)
        if pool_type == 2:
            _x = tf.nn.avg_pool(_x, [1, 2, 2, 1], [1, 2, 2, 1], "VALID")
        elif pool_type == 1:
            _x = tf.nn.avg_pool(_x, [1, 2, 2, 1], [1, 2, 1, 1], "SAME")
        elif pool_type == 3:
            _x = tf.nn.avg_pool(_x, [1, 2, 2, 1], [1, 1, 2, 1], "SAME")
        return _x, filters

    @staticmethod
    def _stacked_bidirectional_rnn(rnn, num_units, num_layers, inputs, seq_lengths):
        """
        multi layer bidirectional rnn
        :param rnn: RNN class, e.g. LSTMCell
        :param num_units: int, hidden unit of RNN cell
        :param num_layers: int, the number of layers
        :param inputs: Tensor, the input sequence, shape: [batch_size, max_time_step, num_feature]
        :param seq_lengths: list or 1-D Tensor, sequence length, a list of sequence lengths, the length of the list is batch_size
        :return: the output of last layer bidirectional rnn with concatenating
        """
        _inputs = inputs
        if len(_inputs.get_shape().as_list()) != 3:
            raise ValueError("the inputs must be 3-dimensional Tensor")

        for _ in range(num_layers):
            with tf.variable_scope(None, default_name="bidirectional-rnn"):
                rnn_cell_fw = rnn(num_units)
                rnn_cell_bw = rnn(num_units)
                (output, state) = tf.nn.bidirectional_dynamic_rnn(
                    rnn_cell_fw,
                    rnn_cell_bw,
                    _inputs,
                    seq_lengths,
                    dtype=tf.float32
                )
                _inputs = tf.concat(output, 2)

        return _inputs

    # def _batch_norm(self, name, x):
    #     with tf.variable_scope(name):
    #
    #         # Get the last dimension of tensor, the mean after, the variance is this dimension
    #         params_shape = [x.get_shape()[-1]]
    #
    #         # Normalized data is the mean value of 0 after the variance is 1,
    #         # - there is also an adjustment of x = x * gamma + beta
    #         # This will continue to adjust with training
    #         beta = tf.get_variable(
    #             'beta', params_shape, tf.float32,
    #             initializer=tf.constant_initializer(0.0, tf.float32))
    #         gamma = tf.get_variable(
    #             'gamma', params_shape, tf.float32,
    #             initializer=tf.constant_initializer(1.0, tf.float32))
    #
    #         # When training, constantly adjust the smoothing mean, smoothing the variance
    #         # In the prediction process, the adjusted smooth variance mean is used for standardization during training.
    #         if self.mode == RunMode.Trains:
    #             # Get batch average and variance, size[Last Dimension]
    #             mean, variance = tf.nn.moments(x, [0, 1, 2], name='moments')
    #
    #             # These two names, moving_mean and moving_variance must be equal to both training and prediction
    #             # - get_variable() can be used to create shared variables
    #             moving_mean = tf.get_variable(
    #                 'moving_mean', params_shape, tf.float32,
    #                 initializer=tf.constant_initializer(0.0, tf.float32),
    #                 trainable=False)
    #             moving_variance = tf.get_variable(
    #                 'moving_variance', params_shape, tf.float32,
    #                 initializer=tf.constant_initializer(1.0, tf.float32),
    #                 trainable=False)
    #
    #             self._extra_train_ops.append(moving_averages.assign_moving_average(
    #                 moving_mean, mean, 0.9))
    #             self._extra_train_ops.append(moving_averages.assign_moving_average(
    #                 moving_variance, variance, 0.9))
    #         else:
    #             mean = tf.get_variable(
    #                 'moving_mean', params_shape, tf.float32,
    #                 initializer=tf.constant_initializer(0.0, tf.float32),
    #                 trainable=False)
    #             variance = tf.get_variable(
    #                 'moving_variance', params_shape, tf.float32,
    #                 initializer=tf.constant_initializer(1.0, tf.float32),
    #                 trainable=False)
    #
    #             tf.summary.histogram(mean.op.name, mean)
    #             tf.summary.histogram(variance.op.name, variance)
    #
    #         x_bn = tf.nn.batch_normalization(x, mean, variance, beta, gamma, 0.001)
    #         x_bn.set_shape(x.get_shape())
    #
    #         return x_bn

    def _batch_norm(self, name, x):
        with tf.variable_scope(name):
            # 输入通道维数
            params_shape = [x.get_shape()[-1]]
            # offset
            beta = tf.get_variable('beta',
                                   params_shape,
                                   tf.float32,
                                   initializer=tf.constant_initializer(0.0, tf.float32))
            # scale
            gamma = tf.get_variable('gamma',
                                    params_shape,
                                    tf.float32,
                                    initializer=tf.constant_initializer(1.0, tf.float32))

            if self.mode == RunMode.Trains:
                # 为每个通道计算均值、标准差
                mean, variance = tf.nn.moments(x, [0, 1, 2], name='moments')
                # 新建或建立测试阶段使用的batch均值、标准差
                moving_mean = tf.get_variable('moving_mean',
                                              params_shape, tf.float32,
                                              initializer=tf.constant_initializer(0.0, tf.float32),
                                              trainable=False)
                moving_variance = tf.get_variable('moving_variance',
                                                  params_shape, tf.float32,
                                                  initializer=tf.constant_initializer(1.0, tf.float32),
                                                  trainable=False)
                # 添加batch均值和标准差的更新操作(滑动平均)
                # moving_mean = moving_mean * decay + mean * (1 - decay)
                # moving_variance = moving_variance * decay + variance * (1 - decay)
                self._extra_train_ops.append(moving_averages.assign_moving_average(
                    moving_mean, mean, 0.9))
                self._extra_train_ops.append(moving_averages.assign_moving_average(
                    moving_variance, variance, 0.9))
            else:
                # 获取训练中积累的batch均值、标准差
                mean = tf.get_variable('moving_mean',
                                       params_shape, tf.float32,
                                       initializer=tf.constant_initializer(0.0, tf.float32),
                                       trainable=False)
                variance = tf.get_variable('moving_variance',
                                           params_shape, tf.float32,
                                           initializer=tf.constant_initializer(1.0, tf.float32),
                                           trainable=False)
                # 添加到直方图总结
                tf.summary.histogram(mean.op.name, mean)
                tf.summary.histogram(variance.op.name, variance)

            # BN层：((x-mean)/var)*gamma+beta
            y = tf.nn.batch_normalization(x, mean, variance, beta, gamma, 0.001)
            y.set_shape(x.get_shape())
            return y
