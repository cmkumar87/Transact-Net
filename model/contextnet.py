import torchwordemb
import torch
import torchvision
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import tqdm
from torch.autograd import Variable
from torchvision import transforms, utils
import re
import os
#import torchtext

from sklearn.model_selection import train_test_split
#from torchtext.data import Field
#from torchtext.data import TabularDataset, Iterator, BucketIterator

import pandas as pd
import numpy as np
#from visualize_attention import attentionDisplay
from sklearn import metrics
#import matplotlib.pyplot as plt
import spacy
from spacy.lang.en import English

import argparse

MAX_SEQUENCE_LENGTH = 250 #250 words per post
MAX_THREAD_LENGTH = 15
MAX_NB_WORDS = 20000
VALIDATION_SPLIT = 0.2
MINI_BATCH_SIZE = 32
num_epochs = 10

parser = argparse.ArgumentParser(description='BiLSTM model for predicting instructor internvention')
parser.add_argument('-d','--dim',help="dimension of the embedding. 50 or 300", default=50, required=False, type=int)
parser.add_argument('-v','--val',help="validation split: a number between 0 to 1", default=0.2, required=False, type=int)
parser.add_argument('-c','--course',help="course id", required=True, type=str)
parser.add_argument('-i','--ver',help="verbose mode", required=False, type=bool)

args = vars(parser.parse_args())
course = args['course']
EMBEDDING_DIM = args['dim']

input_path = '/diskA/muthu/Transact-Net/feats/in' + course + '_w2v'
print(input_path)

#vocab, vec = torchwordemb.load_glove_text("/diskA/animesh/glove/glove.6B.50d.txt")

#set seed for reproducibility of results
from numpy.random import seed
seed(1491)

torch.manual_seed(1491)

def tokenize_and_clean(string):
    """
    Tokenization/string cleaning for all datasets except for SST.
    Original taken from https://github.com/yoonkim/CNN_sentence/blob/master/process_data.py
    """
    #for math equations
    string = re.sub(r"\$\$.*?\$\$", " <MATH> ", string)
    string = re.sub(r"\(.*\(.*?\=.*?\)\)", " <MATH> ", string)
    string = re.sub(r"\\\(\\mathop.*?\\\)", " <MATH> ", string)
    string = re.sub(r"\\\[\\mathop.*?\\\]", " <MATH> ", string)
    string = re.sub(r"[A-Za-z]+\(.*?\)", " <MATH> ", string)    
    string = re.sub(r"[A-Za-z]+\[.*?\]", " <MATH> ", string)    
    string = re.sub(r"[0-9][\+\*\\\/\~][0-9]", " <MATH> ", string) 
    string = re.sub(r"<MATH>\s*[\+\-\*\\\/\~][0-9]", " <MATH> ", string) 
        
    string = re.sub(r"<MATH>\s*[\+\-\*\\\/\~\=]", " <MATH> ", string)
    string = re.sub(r"[\+\-\*\\\/\~\=]\s*<MATH>", " <MATH> ", string)
        
    string = re.sub(r"[\+\*\\\/\~]", " <MATH> ", string)    
    string = re.sub(r"(<MATH>\s*)+", " <MATH> ", string)

    #for time 
    string = re.sub(r"[0-9][0-9]?:[0-9][0-9]?", "<TIMEREF>", string)

    #for url's
    string = re.sub(r"https?\:\/\/[a-zA-Z0-9][a-zA-Z0-9\.\_\?\=\/\%\-\~\&]+", "<URLREF>", string)

    # for english sentences 
    string = re.sub(r"[^A-Za-z0-9(),!?\'\`]", " ", string)
    string = re.sub(r"\'s", " \'s", string)
    string = re.sub(r"\'ve", " \'ve", string)
    string = re.sub(r"n\'t", " n\'t", string)
    string = re.sub(r"\'re", " \'re", string)
    string = re.sub(r"\'d", " \'d", string)
    string = re.sub(r"\'ll", " \'ll", string)
    string = re.sub(r",", " , ", string)
    string = re.sub(r"!", " ! ", string)
    string = re.sub(r"\(", " \( ", string)
    string = re.sub(r"\)", " \) ", string)
    string = re.sub(r"\?", " \? ", string)
    string = re.sub(r"\s{2,}", " ", string)
    
    string =  string.strip().lower()
    #return string
    nlp = spacy.load('en')
    tokenizer = English().Defaults.create_tokenizer(nlp)
    return [tok.text for tok in tokenizer(string)]

df = pd.read_csv(input_path, sep='\t', header=None)
train,test = train_test_split(df, test_size=0.2, random_state=1491, shuffle=True)

#X_train = (train.to_frame().T)
X_train = train[2]
y_train = train[1]
X_test = test[2]
y_test =  test[1]

## Load pretrained word vector

if args['dim'] == 50:
	print('loading 50d glove embedding')
	vocab, vec = torchwordemb.load_glove_text("/diskA/animesh/glove/glove.6B.50d.txt")
elif args['dim'] == 300:
	print('loading 300d glove embedding')
	vocab, vec = torchwordemb.load_glove_text("/diskA/animesh/glove/glove.6B.300d.txt")
else:
	print("Embedding dimension not available. Defaulting to 50 dimensions")
	vocab, vec = torchwordemb.load_glove_text("/diskA/animesh/glove/glove.6B.50d.txt")

max_idx = len(vocab)

for word in ['<unk>', '<timeref>', '<math>', '<mathfunc>', '<eop>', '<urlref>']:
	max_idx += 1
	k = np.random.rand(1, EMBEDDING_DIM)
	k = 7*k/np.linalg.norm(k)
	vocab[word]= max_idx
	
	k_tensor = torch.from_numpy(k)
	k_tensor = k_tensor.type(torch.FloatTensor)
	vec = torch.cat((k_tensor,vec), 0)

if args['ver']:
    print(vec.size())

embed = nn.Embedding(max_idx, EMBEDDING_DIM)
embed.weight = nn.Parameter(vec)

#switch to freeze word embedding training
embed.weight.requires_grad = False

conv_bloc = nn.Sequential(nn.Conv1d(in_channels=EMBEDDING_DIM, out_channels=128, kernel_size=5, padding=2)
                    ,nn.ReLU()
                    #,nn.MaxPool1d(kernel_size=25, padding=1)
                    #,nn.BatchNorm1d(128)
                    #,nn.Conv1d(128, 32, kernel_size=5, padding=1)
                    #,nn.ReLU()
                    ,nn.MaxPool1d(kernel_size=5, padding=2, stride=5)
                   )

lstm = nn.LSTM(input_size=128, hidden_size=64)
fc1 = nn.Sequential(nn.Linear(64, 64)
                    ,nn.ReLU()
                    ,nn.Dropout(p=0.4)
                   )

fc2 = nn.Sequential(nn.Linear(64, 2)
                    ,nn.Softmax()
                   )
if args['ver']:
    print(conv_bloc)
    print(fc1)
    print(fc2)

#test input
inp = torch.tensor([[vocab["hello"], vocab["world"], vocab["english"],vocab["hello"], vocab["world"], vocab["english"],
                     vocab["hello"], vocab["world"], vocab["english"],vocab["hello"], vocab["world"], vocab["english"],
                     vocab["hello"], vocab["world"], vocab["english"],vocab["hello"], vocab["world"], vocab["english"],
                     vocab["hello"], vocab["world"], vocab["english"],vocab["hello"], vocab["world"], vocab["english"]]], dtype=torch.long)

loss_fn = nn.CrossEntropyLoss()
optimizer = optim.Adam(list(conv_bloc.parameters()) + list(lstm.parameters()) + list(fc1.parameters()) + list(fc2.parameters()), lr=0.0001)

for epoch in range(1):
    total_loss = torch.Tensor([0])
    for idx in list(X_train.index.values):
        x_tkns = tokenize_and_clean(X_train[idx])

        word_idxs = torch.tensor([vocab[w] if w in vocab else vocab['<unk>'] for w in x_tkns], dtype=torch.long)
        word_idxs = word_idxs.reshape(1,-1)
        inp = Variable(word_idxs)
        
        if args['ver']:
            print(inp)

        target = Variable(torch.LongTensor([y_train[idx]]), requires_grad=False)

        if args['ver']:
             print(inp.size())

        inp = embed(inp)

        if args['ver']:
             print(inp.size())
             print(inp)

        inp = inp.transpose(1,2)

        if args['ver']:
            print(inp.size())

        op = conv_bloc(inp)

        if args['ver']:
            print("after conv bloc" + str(op.size()))

        op = op.permute(2,0,1)

        if args['ver']:
            print(op.size())

        h_n, _ = lstm(op)

        if args['ver']:
            print("after lstm" + str(op.size()))
        
        h_n = h_n.permute(1,0,2)

        if args['ver']:
            print(op.size())

        op = fc1(h_n[:,-1,:])

        if args['ver']:
            print(op.size())

        op = fc2(op)

        if args['ver']:
            print('Final op size:' + str(op.size()))
            print('Final ouput at epoch #'+ str(epoch) + str(op))
        
        #test target
        #target = torch.rand_like(op)

        loss = loss_fn(op, target)
        
        print(idx, loss.item())
            
        # Zero the gradients before running the backward pass.
        optimizer.zero_grad()

        loss.backward()
        optimizer.step()

        if args['ver']:
            print('Final op size:' + str(op.size()))
            print('Final ouput at epoch #'+ str(epoch) + str(op))
