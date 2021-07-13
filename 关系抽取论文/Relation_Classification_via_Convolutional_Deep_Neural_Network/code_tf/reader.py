import tensorflow as tf 
from collections import namedtuple
from collections import OrderedDict
import os
import numpy as np


FLAGS = tf.app.flags.FLAGS
PAD_WORD = '<pad>'
raw_example = namedtuple('raw_example', 'label entity1 entity2 sentence')
position_pair = namedtuple('position_pair', 'first last')

def load_raw_data(filename, is_test=False):
    """
    return a list of raw_example(label, entity1 entity2 sentence):
        label: int
        entity1: namedtuple(first last), first and last are int.
        entity2: namedtuple(first last), first and last are int.
        sentence: a list of tokens
    """
    data = []
    with open(filename) as f:
        for line in f:
            words = line.strip().split(' ')
            # words are list, from index 5 are sentence
            sent = words[5:]
            # max_len
            sent_length = len(sent)
            if not is_test:
                if FLAGS.max_len < sent_length:  # 更新max_len，使其为最大的句子长度
                    FLAGS.max_len = sent_length
            # label
            label = int(words[0])  # word的第0个是label值
            # entity1, entity2
            entity1 = position_pair(int(words[1]), int(words[2]))
            entity2 = position_pair(int(words[3]), int(words[4]))
            # example
            example = raw_example(label, entity1, entity2, sent)
            data.append(example)
        return data


def build_vocab(raw_train_data, raw_valid_data, vocab_file):
    if not os.path.exists(vocab_file):
        vocab = set()
        for example in raw_train_data + raw_valid_data:  # 遍历训练集和测试集每个example
            for word in example.sentence:  # 遍历每个example的每个token
                vocab.add(word)  # 集合，如果存在word，就不加，不存在，加
        with open(vocab_file, 'w') as f:
            for word in sorted(list(vocab)):  # 按照词字母排序后遍历
                f.write('{}\n'.format(word))
                f.flush()
            f.write('{}\n'.format('UNK'))
            f.flush()
            f.write('{}\n'.format(PAD_WORD))  # 最后加上一个pad
            f.flush()


def trim_embeddings(vocab_file, 
                    pretrain_embed_file, 
                    pretrain_words_file, 
                    modify_embed_file):
    """
    最终需要一个词向量矩阵的npy文件和一个对应的vocab.txt的词汇表文件
    """
    if not os.path.exists(modify_embed_file):
        pretrain_embed, pretrain_words2id = _load_embedding(pretrain_embed_file, 
                                                            pretrain_words_file)
        word_embed = []
        vocab = _load_vocab(vocab_file)
        for word in vocab:
            if word in pretrain_words2id:
                id_ = pretrain_words2id[word]  # 如果vocab中的单词在预训练的词表，取出id
                word_embed.append(pretrain_embed[id_])  # 取出对应的词向量
            else:
                vec = np.random.normal(0, 0.1, [FLAGS.word_dim])  # 不在就随机初始化
                word_embed.append(vec)
        pad_id = -1  # for循环最后一个是pad，随机初始化了，现在改为0向量
        word_embed[pad_id] = np.zeros([FLAGS.word_dim])
        # 两种转化np.array的方式都可以
        # word_embed = np.asarray(word_embed)
        word_embed = np.array(word_embed)
        np.save(modify_embed_file, word_embed.astype(np.float32))

    word_embed, vocab2id = _load_embedding(modify_embed_file, vocab_file)
    return word_embed, vocab2id


def perfect_embeddings(vocab_file, 
                       pretrain_embed_file, 
                       pretrain_words_file, 
                       modify_embed_file):
    if not os.path.exists(modify_embed_file):
        pretrain_embed, pretrain_words2id = _load_embedding(pretrain_embed_file, 
                                                            pretrain_words_file)

        if PAD_WORD not in pretrain_words2id:
            pretrain_words2id[PAD_WORD] = len(pretrain_words2id)
            modify_embed = np.row_stack((pretrain_embed, np.zeros([FLAGS.word_dim])))

        if "UNK" not in pretrain_words2id:
            pretrain_words2id["UNK"] = len(pretrain_words2id)
            modify_embed = np.row_stack((modify_embed, np.random.normal(0, 0.1, [FLAGS.word_dim])))

        np.save(modify_embed_file, modify_embed.astype(np.float32))
        with open(FLAGS.vocab_file, 'w') as f:
            for key in pretrain_words2id.keys():
                f.write('{}\n'.format(key))
                f.flush()
    word_embed, vocab2id = _load_embedding(modify_embed_file, vocab_file)
    return word_embed, vocab2id


def _load_embedding(embed_file, words_file): 
    """
    return: embed, words2id
        embed: 加载的词向量矩阵，np.array
        words2id: 加载词向量矩阵对应的词表，并转化为dict形式，key为token，value为index
    """
    embed = np.load(embed_file)  # numpy.array类型的词向量矩阵
    words2id = {}
    words = _load_vocab(words_file)
    for id_, word in enumerate(words):
        words2id[word] = id_
    return embed, words2id


def _load_vocab(words_file):
    words = []
    with open(words_file) as f:
        for line in f:
            words.append(line.strip())
    return words


def map_words_to_id(raw_data, word2id):
    """
    inplace convert sentence from a list of words to a list of ids
    """
    pad_id = word2id[PAD_WORD]
    unk_id = word2id['UNK']
    for raw_example in raw_data:  # 遍历每个样本
        for idx, word in enumerate(raw_example.sentence):  # 遍历样本的sentence进行replace
            raw_example.sentence[idx] = word2id.get(word, unk_id)
        
        if len(raw_example.sentence) < FLAGS.max_len:
            # pad the sentence to FLAGS.max_len
            pad_n = FLAGS.max_len - len(raw_example.sentence)
            raw_example.sentence.extend(pad_n * [pad_id])
        else:
            # 截断
            raw_example = raw_example._replace(sentence=raw_example.sentence[0: FLAGS.max_len])


def write_tfrecord(raw_data, filename):
    if not os.path.exists(filename):
        writer = tf.python_io.TFRecordWriter(filename)
        for raw_example in raw_data:
            # lexical特征
            lexical = _lexical_feature(raw_example)  # a list 
            lexical_value = tf.train.Feature(int64_list=tf.train.Int64List(value=lexical))
            # 标签信息
            rid = raw_example.label
            rid_value = tf.train.Feature(int64_list=tf.train.Int64List(value=[rid]))
            # 句子信息
            sentence = raw_example.sentence
            sentence_value = tf.train.Feature(int64_list=tf.train.Int64List(value=sentence))
            # 位置信息
            position1, position2 = _position_feature(raw_example)
            position1_value = tf.train.Feature(int64_list=tf.train.Int64List(value=position1))
            position2_value = tf.train.Feature(int64_list=tf.train.Int64List(value=position2))
            # 构建feature
            feature = OrderedDict()
            feature['lexical'] = lexical_value
            feature['rid'] = rid_value
            feature['sentence'] = sentence_value
            feature['position1'] = position1_value
            feature['position2'] = position2_value
            features = tf.train.Features(feature=feature)
            # 构建tf_example
            tf_example = tf.train.Example(features=features)
            writer.write(tf_example.SerializeToString())
        writer.close() 


def _lexical_feature(raw_example):

    def _entity_context(e_idx, sent):
        # return [id of word(entity), id of word(entity - 1), id of word(entity + 1)]
        context = []
        context.append(sent[e_idx])  # 添加entity本身的id
        # 添加entity上一个词的id
        if e_idx >= 1:
            context.append(sent[e_idx - 1])
        else:
            context.append(sent[e_idx])  # 如果entity本身就是第1个词，则词本身作为上一个词
        # 添加entity下一个词的id
        if e_idx < len(sent) - 1:
            context.append(sent[e_idx + 1])
        else:
            context.append(sent[e_idx])
        return context

    e1_idx = raw_example.entity1.first
    e2_idx = raw_example.entity2.first
    context1 = _entity_context(e1_idx, raw_example.sentence)
    context2 = _entity_context(e2_idx, raw_example.sentence)
    # 忽略论文中的上位词WordNet hypernyms
    lexical = context1 + context2
    return lexical


def _position_feature(raw_example):
    # sentence中每个token相对于entity的距离,entity本身为61，0-60表示在entity左边，62-122在entity右边

    def distance(n):
        if n < -60:  # 如果在entity左边60个词以外
            return 0  # 中间相隔的0个词
        elif n >= -60 and n <= 60:  # 如果在entity左边或者右边60个词以内
            return n + 61  # 中间相隔
        else:
            return 122

    e1_idx = raw_example.entity1.first
    e2_idx = raw_example.entity2.first

    position1 = []
    position2 = []
    for i in range(FLAGS.max_len):
        position1.append(distance(i - e1_idx))
        position2.append(distance(i - e2_idx))
    return position1, position2


def read_tfrecord_to_batch(filename, epoch, batch_size, shuffle=True):
    dataset = tf.data.TFRecordDataset(filename)
    name_to_feature = {'lexical': tf.FixedLenFeature([6], tf.int64),
                       'rid': tf.FixedLenFeature([], tf.int64),
                       'sentence': tf.FixedLenFeature([FLAGS.max_len], tf.int64),
                       'position1': tf.FixedLenFeature([FLAGS.max_len], tf.int64),
                       'position2': tf.FixedLenFeature([FLAGS.max_len], tf.int64)}

    # def _parse_example(record, name_to_feature):
    #     example = tf.parse_single_example(record, name_to_feature)
    #     return example
    def _parse_example(record, name_to_feautre):
        example = tf.parse_single_example(record, name_to_feautre)
        for name in list(example.keys()):
            temp = example[name]
            if temp.dtype == tf.int64:
                temp = tf.to_int32(temp)
            example[name] = temp
        return example

    dataset = dataset.map(lambda record: _parse_example(record, name_to_feature))
    dataset = dataset.repeat(epoch)
    if shuffle:
        dataset = dataset.shuffle(buffer_size=100)
    dataset = dataset.batch(batch_size, drop_remainder=FLAGS.drop_remainder)
    iterator = dataset.make_one_shot_iterator()
    batch = iterator.get_next()
    return batch


def get_inputs():
    # 读取原始数据，将标签、句子、entity处理成namedtuple形式，return a list of namedtuples
    raw_train_data = load_raw_data(FLAGS.train_file)
    raw_valid_data = load_raw_data(FLAGS.valid_file)
    raw_test_data = load_raw_data(FLAGS.test_file, is_test=True)
    train_length = len(raw_train_data)
    valid_length = len(raw_valid_data)
    test_length = len(raw_test_data)
    print('train sample nums: %d, valid sample nums: %d, test sample nums: %d' % 
        (train_length, valid_length, test_length))

    # 选择一种构造词向量的方式
    # 方式一：对预训练词向量进行剪枝
    # 利用训练集和验证集构建vocab.txt(词汇表，结构同bert)
    # build_vocab(raw_train_data, raw_valid_data, FLAGS.vocab_file)
    # 预训练的words可能远多于训练集和测试集加起来的vocab，因此对预训练的词向量进行“剪枝”
    # 去掉没用到的token及其所对应的词向量。
    # word_embed, vocab2id = trim_embeddings(FLAGS.vocab_file,
    #                                       FLAGS.senna_embed50_file,
    #                                       FLAGS.senna_words_file,
    #                                       FLAGS.modify_embed50_file)
    # 方式二：对预训练词向量进行修改，添加pad、unk等
    word_embed, vocab2id = perfect_embeddings(FLAGS.vocab_file,
                                              FLAGS.senna_embed50_file,
                                              FLAGS.senna_words_file,
                                              FLAGS.modify_embed50_file)
    # map words to ids
    map_words_to_id(raw_train_data, vocab2id)
    map_words_to_id(raw_valid_data, vocab2id)
    map_words_to_id(raw_test_data, vocab2id)
    # convert raw data to TFRecord format data and write to file
    write_tfrecord(raw_train_data, FLAGS.train_record)
    write_tfrecord(raw_valid_data, FLAGS.valid_record)
    write_tfrecord(raw_test_data, FLAGS.test_record)
    # 读取TFRecord
    train_data = read_tfrecord_to_batch(FLAGS.train_record, FLAGS.num_epochs, 
                                        FLAGS.batch_size, shuffle=True)
    # 预测num_epochs次，每次预测全部，测试集数量为2717
    valid_data = read_tfrecord_to_batch(FLAGS.valid_record, FLAGS.num_epochs, 
                                       len(raw_valid_data), shuffle=False) 
    test_data = read_tfrecord_to_batch(FLAGS.test_record, 1, 
                                       len(raw_test_data), shuffle=False) 
    return train_data, valid_data, test_data, word_embed, train_length, valid_length, test_length





