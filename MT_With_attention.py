# -*- coding: utf-8 -*-
"""Sq2Sq.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/16NmjnvftqlEHWN2LRKVm6_FvHudR1IZA
"""

!python -m spacy download de_core_news_sm

import numpy as np
import torch
from torch.nn import *
from torch.nn.functional import *
from torchtext.legacy.datasets import Multi30k
from torchtext.legacy.data import Field,BucketIterator
import spacy
import random
import torch.optim as opt
device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
device

eng=spacy.load('en')
ger=spacy.load('de_core_news_sm')

def Tokenize_eng(text):
  return [a.text for a in eng.tokenizer(text)]
def Tokenize_german(text):
  return [b.text for b in ger.tokenizer(text)]

german=Field(tokenize=Tokenize_german,lower=True,init_token='<sos>',eos_token='<eos>')
english=Field(tokenize=Tokenize_eng,lower=True,init_token='<sos>',eos_token='<eos>')

Train,Val,Test=Multi30k.splits(exts=('.de','.en'),fields=(german,english))

german.build_vocab(Train,max_size=10000,min_freq=2)
english.build_vocab(Train,max_size=10000,min_freq=2)

##building encoder
class Encoder(Module):
  def __init__(self,inp_size,emd_size,hidden_size):
    super(Encoder,self).__init__()
    self.inp_size=inp_size
    self.emd_size=emd_size
    self.hidden_size=hidden_size
    self.drop=Dropout(0.5)
    self.embed=Embedding(self.inp_size,self.emd_size)
    self.lstm=LSTM(self.emd_size,self.hidden_size,bidirectional=True)
    self.fc_hidden=Linear(self.hidden_size*2,self.hidden_size)
    self.fc_cell=Linear(self.hidden_size*2,self.hidden_size)
  def forward(self,x):
    x=self.drop(self.embed(x))
    x,(h,c)=self.lstm(x)
    assert len(h.shape)==3
    h=self.fc_hidden(torch.cat((h[0:1],h[1:2]),dim=2))
    c=self.fc_cell(torch.cat((c[0:1],c[1:2]),dim=2))
    return x,h,c



class AttentionDecoder(Module):
  def __init__(self,vocab,embed_dim,hidden_dim,output_dim):
    super(AttentionDecoder,self).__init__()
    self.embed_dim=embed_dim
    self.hidden_dim=hidden_dim
    self.output_dim=output_dim
    self.embed=Embedding(vocab,self.embed_dim)
    self.lstm=LSTM(self.embed_dim+self.hidden_dim*2,self.hidden_dim)
    self.attention_1=Linear(self.hidden_dim*3,64)
    self.attention_2=Linear(64,1)
    self.softmax=Softmax(dim=0)
    self.l1=Linear(self.hidden_dim,64)
    self.l2=Linear(64,256)
    self.l3=Linear(256,self.output_dim)
  def forward(self,x,states,h,c):
    x=x.unsqueeze(0)
    x=self.embed(x)
    seq_len=states.shape[0]
    h_reshaped=h.repeat(seq_len,1,1)
    energy=relu(self.attention_1(torch.cat((h_reshaped,states),dim=2)))
    energy=relu(self.attention_2(energy))
    attention=self.softmax(energy)
    #print(f'Attention matrix {attention}')
    attention=attention.permute(1,2,0)
    states=states.permute(1,0,2)
    calc=torch.bmm(attention,states).permute(1,0,2)
    x=torch.cat((calc,x),dim=2)
    #print(f'shape of feed {x.shape}')
    x,(h,c)=self.lstm(x,(h,c))
    x=relu(self.l1(x))
    x=relu(self.l2(x))
    x=self.l3(x)
    x=x.squeeze(0) 
    return x,h,c

class Encoder_Decoder(Module):
  def __init__(self,en,dec):
    super(Encoder_Decoder,self).__init__()
    self.encoder=en;
    self.decoder=dec
  def forward(self,inp,target,ratio=0.5):
    batch_size=inp.shape[1]
    seq_len=target.shape[0]
    vocab=len(english.vocab)
    outputs=torch.zeros((seq_len,batch_size,vocab)).to(device)
    states,h,c=self.encoder(inp)
    x=target[0]
    #autoregression / teacher forcing
    for t in range(1,seq_len):
      output,h,c=self.decoder(x,states,h,c)
      outputs[t]=output
      best_guess=output.argmax(1)
      x=target[t] if random.random()<ratio else best_guess
    return outputs

epochs=60
encoder_vocab=len(german.vocab)
decoder_vocab=len(english.vocab)
embed_encoder=300
embed_decoder=300

TrainD,ValD,TestD=BucketIterator.splits((Train,Val,Test),batch_size=64,sort_within_batch=True,sort_key=lambda x:len(x.src),device=device)

for a,b in TrainD:
  print(a[0].shape,a[1].shape)

encoder_net=Encoder(encoder_vocab,embed_encoder,256).to(device)
decoder_net=AttentionDecoder(decoder_vocab,embed_decoder,256,decoder_vocab).to(device)
Sequence_net=Encoder_Decoder(encoder_net,decoder_net).to(device)



pad_index=english.vocab.stoi['<pad>']
optimizer=opt.Adam(Sequence_net.parameters())
loss_f=CrossEntropyLoss(ignore_index=pad_index)

for i in range(epochs):
  L=0
  Sequence_net.train()
  for batch in TrainD:
    inp=batch.src.to(device)
    targ=batch.trg.to(device)
    output=Sequence_net(inp,targ)
    output=output[1:]
    output=output.reshape(-1,output.shape[-1])
    targ=targ[1:].reshape(-1)
    optimizer.zero_grad()
    loss=loss_f(output,targ)
    loss.backward()
    L+=loss.item()
    torch.nn.utils.clip_grad_norm_(Sequence_net.parameters(),max_norm=1)
    optimizer.step()
  val_loss=evaluate(Sequence_net,TestD,loss_f)
  print(f"Epoch{i+1} has loss {L/len(TrainD)}| val_loss {val_loss}");

def evaluate(model, iterator, criterion):
    
    model.eval()
    
    epoch_loss = 0
    
    with torch.no_grad():
    
        for i, batch in enumerate(iterator):

            src= batch.src
            trg = batch.trg

            output = model(src, trg, 0) #turn off teacher forcing
            
            #trg = [trg len, batch size]
            #output = [trg len, batch size, output dim]

            output_dim = output.shape[-1]
            
            output = output[1:].view(-1, output_dim)
            trg = trg[1:].view(-1)

            #trg = [(trg len - 1) * batch size]
            #output = [(trg len - 1) * batch size, output dim]

            loss = criterion(output, trg)

            epoch_loss += loss.item()
        
    return epoch_loss / len(iterator)

evaluate(Sequence_net,TestD,loss_f)

def translate_sentence(sentence, src_field, trg_field, model, device, max_len = 50):

    model.eval()
        
    if isinstance(sentence, str):
        nlp = spacy.load('de_core_news_sm')
        tokens = [token.text.lower() for token in nlp(sentence)]
    else:
        tokens = [token.lower() for token in sentence]

    tokens = [src_field.init_token] + tokens + [src_field.eos_token]
        
    src_indexes = [src_field.vocab.stoi[token] for token in tokens]
    
    src_tensor = torch.LongTensor(src_indexes).unsqueeze(1).to(device)

    src_len = torch.LongTensor([len(src_indexes)])
    
    with torch.no_grad():
        encoder_outputs, hidden = model.encoder(src_tensor)

        
    trg_indexes = [trg_field.vocab.stoi[trg_field.init_token]]

    attentions = torch.zeros(max_len, 1, len(src_indexes)).to(device)
    
    for i in range(max_len):

        trg_tensor = torch.LongTensor([trg_indexes[-1]]).to(device)
                
        with torch.no_grad():
            output, hidden, attention = model.decoder(encoder_outputs,hidden[0],hidden[1])

            
        pred_token = output.argmax(1).item()
        
        trg_indexes.append(pred_token)

        if pred_token == trg_field.vocab.stoi[trg_field.eos_token]:
            break
    
    trg_tokens = [trg_field.vocab.itos[i] for i in trg_indexes]
    
    return trg_tokens[1:], attentions[:len(trg_tokens)-1]

torch.save(Sequence_net,'/content/lol.pt')

sen='Ich schaue gerne Filme im Dunkeln und deshalb habe ich mich für den Film entschieden'
ok=translate_sentence(model=Sequence_net,src_field=german,trg_field=english,device=device,sentence=sen)

def calculate_bleu():
  pass

