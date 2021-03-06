import numpy as np
import tensorflow as tf
from itertools import islice
import dataset as ds
import time
import utils




def processLine(embeddings, str, max_doc_length, max_que_length):
    start_pos, end_pos, doc, que = str.split(';')
    start_pos = int(start_pos)
    end_pos = int(end_pos)
    document = doc.split(' ')
    question = que.split(' ')
    doc_v = embeddings.sentence2Vectors(document, max_doc_length)
    que_v = embeddings.sentence2Vectors(question, max_que_length)
    return start_pos, end_pos, document, question, doc_v, que_v


def processLineBatch(file, embeddings, batch_size, max_sequence_length, max_question_length, 
                     question_ph, document_ph, dropout_rate_ph,
                     doc_len_ph, que_len_ph, start_true_ph, end_true_ph, batch_size_ph, learning_rate_ph, dropout_rate, lrate):
    next_n_lines = list(islice(file, batch_size))
    if not next_n_lines or len(next_n_lines) != batch_size: return None
    q = []
    d = []
    s = []
    e = []
    dl = []
    ql = []
    batch_size_fact = 0;
    for line_ in next_n_lines:
        start_pos, end_pos, document, question, doc_v, que_v = processLine(
            embeddings, line_, max_sequence_length, max_question_length
        )
        if len(document) > max_sequence_length or  len(question) >= max_question_length or start_pos < 0: 
            print("Wrong example. Skip", document[0])
            continue;
        q.append(que_v)
        d.append(doc_v)
        s.append(start_pos)
        e.append(end_pos)
        dl.append(len(document))
        ql.append(len(question))
        batch_size_fact += 1

    feed_dict = {
        question_ph: q, 
        document_ph: d, 
        start_true_ph: s,
        end_true_ph: e,
        doc_len_ph: dl,
        que_len_ph: ql,
        dropout_rate_ph: dropout_rate,
        batch_size_ph: batch_size_fact,
        learning_rate_ph: lrate
        
    }
    if batch_size_fact != batch_size:  print("Batch Size Fact", batch_size_fact)
    return feed_dict

def accuracy(sess, params, accuracy, pr_start_idx, pr_end_idx):
    try:
        acc, starts, ends = sess.run(
            (accuracy, pr_start_idx, pr_end_idx),
            params
        )

        return acc, starts, ends
        #writer.add_summary(stat,  step)
        #print('AVG accuracy', acc)
    except: 
        print("Test Error", params)


def trainStep(sess, feed_dict, writer, 
              train_step, summary_op, 
              step, profiling = False):
    
    run_options = None
    run_metadata = None
    if profiling:
        run_options = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
        run_metadata = tf.RunMetadata()
    start_time = time.time()
    try:
        _, stat = sess.run(
            (train_step,  summary_op),
            feed_dict = feed_dict,
            options=run_options, run_metadata=run_metadata
        )
        writer.add_summary(stat, step)
        #writer.add_summary(stat_train, step)
    except:
        print("Train Error", step)
        

def loss_and_accuracy(start_true, end_true, batch_size, sum_start_scores, sum_end_scores, max_sequence_length):
    # loss and train step
    onehot_labels_start = tf.one_hot(start_true, max_sequence_length)
    onehot_labels_end   = tf.one_hot(end_true, max_sequence_length)

    with tf.name_scope('Loss'):
        loss_start = tf.nn.softmax_cross_entropy_with_logits(
            labels = onehot_labels_start,
            logits = sum_start_scores)
        loss_start = tf.reduce_mean(loss_start)
        loss_end = tf.nn.softmax_cross_entropy_with_logits(
            labels = onehot_labels_end,
            logits = sum_end_scores)
        loss_end = tf.reduce_mean(loss_end)
        sum_loss = loss_start + loss_end
        
    with tf.name_scope('Accuracy'):
        with tf.name_scope('Prediction'):
            pr_start_idx = tf.to_int32(tf.argmax(sum_start_scores, 1))
            pr_end_idx = tf.to_int32(tf.argmax(sum_end_scores, 1))

        with tf.name_scope('Accuracy'):
            #accuracy_avg = tf.py_func(utils.f1_score_int_avg, [pr_start_idx, pr_end_idx, start_true, end_true], tf.float64)
            accuracy = tf.py_func(utils.f1_score_int_list, [pr_start_idx, pr_end_idx, start_true, end_true], tf.float64)
    
    return sum_loss, accuracy, pr_start_idx, pr_end_idx


# iter_start_scores, iter_end_scores is shape of (B, D, number of iterations)
def loss_and_accuracy_v2(start_true, end_true, batch_size, iter_start_scores, iter_end_scores, max_sequence_length, iter_num):
    # loss and train step
    onehot_labels_start = tf.one_hot(start_true, max_sequence_length)
    onehot_labels_end   = tf.one_hot(end_true, max_sequence_length)
    
    def getIterNum(vec):
        a = vec - tf.pad(vec[0:-1], [[0,1]])
        b = tf.pad(vec[1:], [[0,1]])
        c = tf.add(a,b)
        d = tf.abs(tf.subtract(vec, c))
        return tf.argmin(d)
    
    # m is (D, number of iterations)
    #def sliceByEffectiveIter(m):
    #    n = tf.cast(getIterNum(tf.argmax(m, 0)), tf.int32)
    #    return m[0: , 0:n+1]
    
    # m is (D, number of iterations)
    def leaveOnlyLastEffectiveIter(m):
        n = tf.cast(getIterNum(tf.argmax(m, 0)), tf.int32)
        return m[0: , n]
    
        
    
    onehot_labels_start = tf.tile(tf.expand_dims(onehot_labels_start, -1), [1, 1, iter_num])
    onehot_labels_end   = tf.tile(tf.expand_dims(onehot_labels_end, -1), [1, 1, iter_num])
    print("iter_end_scores", iter_end_scores)
    print(onehot_labels_start)
    print(onehot_labels_end)
    start_scores = tf.map_fn(lambda m: leaveOnlyLastEffectiveIter(m), iter_start_scores, dtype=tf.float32)
    end_scores = tf.map_fn(lambda m: leaveOnlyLastEffectiveIter(m), iter_end_scores, dtype=tf.float32)

    with tf.name_scope('Loss'):
        loss_start = tf.nn.softmax_cross_entropy_with_logits(
            labels = onehot_labels_start,
            logits = iter_start_scores,
            dim = 1)
        
        loss_start = tf.reduce_mean(loss_start)
        loss_end = tf.nn.softmax_cross_entropy_with_logits(
            labels = onehot_labels_end,
            logits = iter_end_scores,
            dim = 1)
        loss_end = tf.reduce_mean(loss_end)
        sum_loss = loss_start + loss_end
        
    with tf.name_scope('Accuracy'):
        with tf.name_scope('Prediction'):
            pr_start_idx = tf.to_int32(tf.argmax(start_scores, 1))
            pr_end_idx = tf.to_int32(tf.argmax(end_scores, 1))

        with tf.name_scope('Accuracy'):
            #accuracy_avg = tf.py_func(utils.f1_score_int_avg, [pr_start_idx, pr_end_idx, start_true, end_true], tf.float64)
            accuracy = tf.py_func(utils.f1_score_int_list, [pr_start_idx, pr_end_idx, start_true, end_true], tf.float64)
    
    return sum_loss, accuracy, pr_start_idx, pr_end_idx


    