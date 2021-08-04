import tensorflow as tf 
import os


FLAGS = tf.app.flags.FLAGS


class BaseModel(object):

    @classmethod
    def set_saver(cls):
        cls.saver = tf.train.Saver(var_list=None)
        cls.save_dir = FLAGS.logdir
        cls.save_path = os.path.join(cls.save_dir, 'model')

    @classmethod
    def restore(cls, session):
        ckpt = tf.train.get_checkpoint_state(cls.save_dir)
        cls.saver.restore(session, ckpt.model_checkpoint_path)

    @classmethod
    def save(cls, session, global_step):
        cls.saver.save(session, cls.save_path, global_step)


class CNNModel(BaseModel):

    def __init__(self, word_embed, data, word_dim, pos_num, pos_dim,
                 num_relations, keep_prob, num_filters, lrn_rate, is_train):
        # input_data
        lexical = data['lexical']
        rid = data['rid']
        sentence = data['sentence']
        pos1 = data['position1']
        pos2 = data['position2']

        # embedding initialization
        word_embed = tf.get_variable('word_embed',
                                     initializer=word_embed,
                                     dtype=tf.float32,
                                     trainable=True)
        pos1_embed = tf.get_variable('pos1_embed', shape=[pos_num, pos_dim])
        pos2_embed = tf.get_variable('pos2_embed', shape=[pos_num, pos_dim])

        # embedding lookup
        lexical = tf.nn.embedding_lookup(word_embed, lexical)  # [batch, 6, word_dim]
        lexical = tf.reshape(lexical, [-1, 6*word_dim])  # [batch, 6*word_dim]
        self.labels = tf.one_hot(rid, num_relations)  # [batch, num_relations]
        sentence = tf.nn.embedding_lookup(word_embed, sentence)  # [batch, max_len, word_dim]
        pos1 = tf.nn.embedding_lookup(pos1_embed, pos1)  # [batch, max_len, pos_dim]
        pos2 = tf.nn.embedding_lookup(pos2_embed, pos2)  # [batch, max_len, pos_dim]

        # cnn model
        sent_pos = tf.concat([sentence, pos1, pos2], axis=2)  # [batch, max_len, word_dim+2*pos_dim]
        if is_train:
            sent_pos = tf.nn.dropout(sent_pos, keep_prob)
        feature = self.cnn_forward('cnn', sent_pos, lexical, num_filters)
        feature_size = feature.shape.as_list()[1]
        self.feature = feature

        if is_train:
            feature = tf.nn.dropout(feature, keep_prob)
        # Map the features to 19 classes
        # logits:[batch, num_relations]
        logits, loss_l2 = self.linear_layer('linear_cnn', feature, feature_size,
                                            num_relations, is_regularize=True)
        # 预测
        probabilities = tf.nn.softmax(logits, axis=1)
        prediction = tf.argmax(probabilities, axis=1)
        accuracy = tf.equal(prediction, tf.argmax(self.labels, axis=1))
        accuracy = tf.reduce_mean(tf.cast(accuracy, tf.float32))
        loss_ce = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(
            labels=self.labels, logits=logits))

        self.logits = logits
        self.probabilities = probabilities
        self.prediction = prediction
        self.accuracy = accuracy
        self.loss = loss_ce + 0.01 * loss_l2

        if not is_train:  # 如果不是训练集
            return

        # optimizer: adam优化器
        global_step = tf.Variable(0, trainable=False, name='step', dtype=tf.int32)
        optimizer = tf.train.AdamOptimizer(lrn_rate)
        update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
        with tf.control_dependencies(update_ops):
            self.train_op = optimizer.minimize(self.loss, global_step)
        self.global_step = global_step

        # 指数衰减学习率：效果很差
        # global_step = tf.Variable(0, trainable=False, name='step', dtype=tf.int32)  # gobal_step初始化为0
        # learning_rate = tf.train.exponential_decay(learning_rate=FLAGS.lrn_rate, 
        #                                            global_step=global_step, 
        #                                            decay_steps=10, 
        #                                            decay_rate=2, 
        #                                            staircase=False)  # 这里也需要global_steps参数
        # with tf.control_dependencies(tf.get_collection(tf.GraphKeys.UPDATE_OPS)):
        #     self.train_op = tf.train.GradientDescentOptimizer(learning_rate).minimize(self.loss, global_step=global_step)
        # self.global_step = global_step
        tf.summary.scalar('loss', self.loss)

    def cnn_forward(self, name, sent_pos, lexical, num_filters):
        with tf.variable_scope(name):
            input_= tf.expand_dims(sent_pos, axis=-1)  # [batch, max_len, word_dim+2*pos_dim, 1]
            input_dim = input_.shape.as_list()[2]

            # convolutional layer
            pool_outputs = []
            for filter_size in [3, 4, 5]:
                with tf.variable_scope('conv-%s' % filter_size):
                    conv_weight = tf.get_variable('W1',
                                                  shape=[filter_size, input_dim, 1, num_filters],
                                                  initializer=tf.truncated_normal_initializer(stddev=0.1))
                    conv_bias = tf.get_variable('b1',
                                                shape=[num_filters],
                                                initializer=tf.constant_initializer(0.1))
                    conv = tf.nn.conv2d(input_, conv_weight, 
                                        strides=[1, 1, input_dim, 1], padding='SAME')
                    conv = tf.nn.relu(conv + conv_bias)
                    conv_dim = conv.shape.as_list()[1]
                    pool = tf.nn.max_pool(conv, ksize=[1, conv_dim, 1, 1],
                                          strides=[1, conv_dim, 1, 1],
                                          padding='SAME')
                    pool_outputs.append(pool)  # [batch, 1, 1, num_filters]
            pools = tf.reshape(tf.concat(pool_outputs, 3), [-1, 3*num_filters]) 
            # feature
            if lexical is not None:
                feature = tf.concat([lexical, pools], axis=1)  # [batch, 6*word_dim+3*num_filters]
            return feature

    def linear_layer(self, name, x, in_size, out_size, is_regularize=False):
        with tf.variable_scope(name):
            loss_l2 = tf.constant(0, dtype=tf.float32)
            w = tf.get_variable('linear_w', shape=[in_size, out_size],
                                initializer=tf.truncated_normal_initializer(stddev=0.1))
            b = tf.get_variable('linear_b', [out_size],
                                initializer=tf.constant_initializer(0.1))
            out = tf.nn.xw_plus_b(x, w, b)
            if is_regularize:
                loss_l2 += tf.nn.l2_loss(w) + tf.nn.l2_loss(b)
            return out, loss_l2



def build_train_valid_model(word_embed, train_data, valid_data, test_data):
    with tf.name_scope('Train'):
        with tf.variable_scope('CNNModel', reuse=None):
            m_train = CNNModel(word_embed, train_data, FLAGS.word_dim, FLAGS.pos_num,
                               FLAGS.pos_dim, FLAGS.num_relations, FLAGS.keep_prob,
                               FLAGS.num_filters, FLAGS.lrn_rate, is_train=True)
    with tf.name_scope('Valid'):
        with tf.variable_scope('CNNModel', reuse=True):
            m_valid = CNNModel(word_embed, valid_data, FLAGS.word_dim, FLAGS.pos_num,
                              FLAGS.pos_dim, FLAGS.num_relations, 1.0,
                              FLAGS.num_filters, FLAGS.lrn_rate, is_train=False)
    with tf.name_scope('Test'):
        with tf.variable_scope('CNNModel', reuse=True):
            m_test = CNNModel(word_embed, test_data, FLAGS.word_dim, FLAGS.pos_num,
                              FLAGS.pos_dim, FLAGS.num_relations, 1.0,
                              FLAGS.num_filters, FLAGS.lrn_rate, is_train=False)
    return m_train, m_valid, m_test