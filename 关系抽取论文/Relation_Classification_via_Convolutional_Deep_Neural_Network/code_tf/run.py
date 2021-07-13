import tensorflow as tf 
from reader import get_inputs
from models import build_train_valid_model
import time
import os
import math


flags = tf.app.flags
FLAGS = flags.FLAGS
flags.DEFINE_string('train_file', 'data/train.cln', 'original training file')
flags.DEFINE_string('valid_file', 'data/test.cln', 'original valid file')
flags.DEFINE_string('test_file', 'data/test.cln', 'original test file')
flags.DEFINE_string('vocab_file', 'middle/vocab.txt', 'vocab of train and valid data')
flags.DEFINE_string('senna_embed50_file', 'data/embed50.senna.npy', 'senna words embedding')
flags.DEFINE_string('senna_words_file', 'data/senna_words.lst', 'senna words list')
flags.DEFINE_string('modify_embed50_file', 'middle/embed50.modify.npy', 'trimmed senna embedding')
flags.DEFINE_string('train_record', 'middle/train.tfrecord', 'training file of TFRecord format')
flags.DEFINE_string('valid_record', 'middle/valid.tfrecord', 'valid file of TFRecord format')
flags.DEFINE_string('test_record', 'middle/test.tfrecord', 'test file of TFRecord format')
flags.DEFINE_string('logdir', 'saved_models/', 'where to save the model')
flags.DEFINE_string('graph_path', 'graph/', 'where to save tensorboard')

flags.DEFINE_boolean('drop_remainder', False, 'whether drop remainder when tfrecord batch')
flags.DEFINE_integer('word_dim', 50, 'word embedding size')
flags.DEFINE_integer('max_len', 96, 'max length of sentences')
flags.DEFINE_integer('num_epochs', 20, 'number of epochs')
flags.DEFINE_integer('batch_size', 100, 'batch_size')
flags.DEFINE_integer('pos_num', 123, 'number of position feature')
flags.DEFINE_integer('pos_dim', 5, 'position embedding size')
flags.DEFINE_integer('num_relations', 19, 'number of relations')
flags.DEFINE_integer('num_filters', 100, 'cnn number of output unit')
flags.DEFINE_float('lrn_rate', 1e-3, 'learning rate')
flags.DEFINE_float('keep_prob', 0.5, 'dropout keep probability')


# def trace_runtime(sess, m_train):

def train(sess, m_train, m_valid, train_length, merge_op, train_writer):
    n = 0  # 记录是第几个epoch
    best = 0.0  # 最佳分数
    start_time = time.time()
    orig_begin_time = start_time

    while True:
        try:
            _, loss, acc, global_step, train_summary = sess.run([m_train.train_op, m_train.loss, 
                                                                 m_train.accuracy, m_train.global_step,
                                                                 merge_op])
            train_writer.add_summary(train_summary, global_step)
            if FLAGS.drop_remainder:
                total_cycle_nums = math.floor(train_length * FLAGS.num_epochs / FLAGS.batch_size)
            else:
                total_cycle_nums = math.ceil(train_length * FLAGS.num_epochs / FLAGS.batch_size)

            # if控制了num_epochs次，验证集只能循环num_epochs次
            if global_step % math.ceil(train_length / FLAGS.batch_size) == 0 or global_step == total_cycle_nums:
                n += 1
                now = time.time()
                duration = now - start_time
                start_time = now
                v_acc = sess.run(m_valid.accuracy)
                if best < v_acc:
                    best = v_acc
                    m_train.save(sess, global_step)
                print('Epoch %d, loss %.2f, acc %.2f %.4f, time %.2f' % (n, loss, acc, v_acc, duration))
                # sys.stdout.flush()
        except tf.errors.OutOfRangeError:
            break


def test(sess, m_test):
    m_test.restore(sess)
    accuracy, predictions = sess.run([m_test.accuracy, m_test.prediction])
    print('----------------------------------------')
    print('accuracy: %.4f' % accuracy)


def main(_):
    train_data, valid_data, test_data, word_embed, train_length, valid_length, test_length = get_inputs()
    m_train, m_valid, m_test = build_train_valid_model(word_embed,
                                                       train_data,
                                                       valid_data,
                                                       test_data)
    m_train.set_saver()

    init_op = tf.group(tf.global_variables_initializer(),
                       tf.local_variables_initializer())

    merge_op = tf.summary.merge_all()
    train_writer = tf.summary.FileWriter(FLAGS.graph_path)

    with tf.Session() as sess:
        sess.run(init_op)
        print('=' * 80)
        train(sess, m_train, m_valid, train_length, merge_op, train_writer)
        test(sess, m_test)



if __name__ == '__main__':
    gpus = tf.config.experimental.list_physical_devices(device_type='GPU')
    for gpu in gpus:
        tf.config.experimental.set_memory_growth(gpu, True)
    tf.app.run()

