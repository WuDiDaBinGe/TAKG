# -*- coding: utf-8 -*-
# @Time    : 2021/11/18 下午11:06
# @Author  : WuDiDaBinGe
# @FileName: HierAttention.py
# @Software: PyCharm
import torch
import torch.nn as nn
import torch.nn.functional as F


class Attention(nn.Module):
    def __init__(self, decoder_size, memory_bank_size, topic_num):
        """Bahdanau style attention"""
        super(Attention, self).__init__()
        self. v = nn.Linear(decoder_size, 1, bias=False)
        self.decode_project = nn.Linear(decoder_size, decoder_size, bias=False)
        self.memory_project = nn.Linear(memory_bank_size, decoder_size, bias=False)
        self.topic_project = nn.Linear(topic_num, decoder_size, bias=False)

    def score(self, memory_bank, decoder_state, topic_dist):
        batch_size, max_input_seq_len, memory_bank_size = memory_bank.size()
        decoder_size = decoder_state.size(1)
        encoder_feature = self.memory_project(memory_bank)  # [batch_size, max_input_seq_len, decoder size]

        dec_feature = self.decode_project(decoder_state)  # [batch_size, decoder_size]
        dec_feature_expanded = dec_feature.unsqueeze(1).expand(batch_size, max_input_seq_len, decoder_size).contiguous()

        topic_feature = self.topic_project(topic_dist)
        topic_feature_expanded = topic_feature.unsqueeze(1).expand(batch_size, max_input_seq_len,
                                                                   decoder_size).contiguous()

        att_features = encoder_feature + dec_feature_expanded + topic_feature_expanded  # [batch_size, max_input_seq_len, decoder_size]
        # TODO: need to use topic features
        # att_features = encoder_feature + dec_feature_expanded
        e = att_features.tanh()  # [batch_size, max_input_seq_len, decoder_size]
        scores = self.v(e).squeeze(-1)  # [batch_size, max_input_seq_len]
        return scores

    def forward(self, decoder_state, memory_bank, src_mask=None):
        """
        :param decoder_state: [batch_size, decoder_size]
        :param memory_bank: [batch_size, max_input_seq_len, memory_bank_size]
        :param src_mask: [batch_size, max_input_seq_len]
        :return:
            context: [batch_size, memory_bank_size]
            attn_dist: [batch_size, max_input_seq_len]
        """
        # init dimension info
        batch_size, max_input_seq_len, memory_bank_size = memory_bank.size()

        scores = self.score(memory_bank, decoder_state)  # [batch_size, max_input_seq_len]
        # don't attend over padding
        if src_mask is not None:
            scores.masked_fill_(src_mask.eq(0), float('-inf'))
        attn_dist = F.softmax(scores, dim=-1)  # [batch_size, max_input_seq_len]

        # Compute weighted sum of memory bank features
        attn_dist = attn_dist.unsqueeze(1)  # [batch_size, 1, max_input_seq_len]
        context = torch.bmm(attn_dist, memory_bank)  # [batch_size, 1, memory_bank_size]

        context = context.squeeze(1)  # [batch_size, memory_bank_size]
        attn_dist = attn_dist.squeeze(1)  # [batch_size, max_input_seq_len]
        assert attn_dist.size() == torch.Size([batch_size, max_input_seq_len])
        assert context.size() == torch.Size([batch_size, memory_bank_size])
        return context, attn_dist


class HierAttention(nn.Module):
    def __init__(self, decoder_size, memory_bank_size, topic_num):
        super(HierAttention, self).__init__()
        self.v = nn.Linear(decoder_size, 1, bias=False)
        self.decode_project = nn.Linear(decoder_size, decoder_size, bias=False)
        self.topic_project = nn.Linear(topic_num, decoder_size, bias=False)
        self.memory_project = nn.Linear(memory_bank_size, decoder_size, bias=False)
        self.doc_attention = Attention(decoder_size, memory_bank_size, topic_num)

    def score(self, memory_bank, decoder_state, topic_dist):
        """
        :param memory_bank: [batch_size, max_input_seq_len1, max_input_seq_len2, hidden]
        :param decoder_state: [batch_size, decoder_size]
        :return: score: [batch_size, max_input_seq_len1, max_input_seq_len2]
        """
        batch_size, max_input_seq_len1, max_input_seq_len2, memory_bank_size = memory_bank.size()
        decoder_size = decoder_state.size(1)

        encoder_feature = self.memory_project(memory_bank)
        # project decoder state
        dec_feature = self.decode_project(decoder_state)  # [batch_size, decoder_size]
        dec_feature_expanded = dec_feature.unsqueeze(1).unsqueeze(1). \
            expand(batch_size, max_input_seq_len1, max_input_seq_len2, decoder_size).contiguous()
        # project topic_dist state
        topic_features = self.topic_project(topic_dist)
        topic_features_expanded = topic_features.unsqueeze(1).unsqueeze(1). \
            expand(batch_size, max_input_seq_len1, max_input_seq_len2, decoder_size).contiguous()

        att_features = encoder_feature + dec_feature_expanded + topic_features_expanded
        # TODO: need to use topic features
        # att_features = encoder_feature + dec_feature_expanded
        e = att_features.tanh()  # [batch_size,max_input_seq_len1, max_input_seq_len2,decoder_size]
        scores = self.v(e).squeeze(-1)  # [batch_size,max_input_seq_len1, max_input_seq_len2]
        return scores

    def forward(self, decoder_state, doc_memory, word_memory, topic_dist, doc_mask, word_mask):
        # init dimension info
        batch_size, max_input_seq_len1, max_input_seq_len2, memory_bank_size = word_memory.size()

        word_scores = self.score(word_memory, decoder_state,
                                 topic_dist)  # [batch_size,max_input_seq_len1, max_input_seq_len2]
        doc_scores = self.doc_attention.score(doc_memory, decoder_state, topic_dist)  # [batch_size,max_input_seq_len1]

        # don't attend over padding
        if word_mask is not None:
            word_scores.masked_fill_(word_mask.eq(0), float('-inf'))
        word_attn_dist = F.softmax(word_scores, dim=-1)  # [batch_size, max_input_seq_len1, max_input_seq_len2, 1]

        # don't attend over padding
        if doc_mask is not None:
            doc_scores.masked_fill_(doc_mask.eq(0), float('-inf'))
        doc_attn_dist = F.softmax(doc_scores, dim=-1)  # [batch_size, max_input_seq_len1, 1]

        # Compute weighted sum of memory bank features
        rescaled_word_attn = doc_attn_dist.unsqueeze(-1) * word_attn_dist
        context = torch.einsum("baqw,bqwd->bad", [rescaled_word_attn.unsqueeze(1), word_memory])
        context = context.squeeze(1)  # [batch_size, memory_bank_size]

        assert rescaled_word_attn.size() == torch.Size([batch_size, max_input_seq_len1, max_input_seq_len2])
        assert context.size() == torch.Size([batch_size, memory_bank_size])

        return context, rescaled_word_attn
