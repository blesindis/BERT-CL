import torch.nn as nn
import base_models
from transformers import BertConfig
from Dataset import ACLForLM_small, RestaurantForLM_small
from Dataset import Wikitext
from accelerate import Accelerator
from torch.utils.tensorboard import SummaryWriter
from transformers import BertConfig, get_cosine_schedule_with_warmup
import torch.optim as optim
from sklearn.preprocessing import StandardScaler

import torch
import numpy as np
import random


def set_seed(seed: int) -> None:
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)
    random.seed(seed)
    torch.backends.cudnn.deterministic = True


def validate(model, val_loader, accelerator):
    losses = []
    for i, batch in enumerate(val_loader):        
        with torch.no_grad():
            batch.to('cuda')
            loss, loss_dict, layer_outputs = model(**batch)
        losses.append(accelerator.gather(loss.repeat(len(batch))))
    
    losses = torch.cat(losses)[:len(val_loader.dataset)]
    perplexity = torch.mean(losses)
    # perplexity = torch.exp(perplexity)
    
    return perplexity


def load_layer_data(path):
    layer_data_dict = torch.load(path, map_location='cuda')
    layer_data = list(layer_data_dict.values())
    return layer_data


def train(
    # model/data params
    model=None, 
    num_epochs=10, 
    dataset=None, 
    dataset_pre=None,
    train_on_newdata=True,
    replay_layerwise=True,
    replay_decoder=False
):
    train_loader, val_loader = dataset.train_loader, dataset.val_loader
    pre_test_loader = dataset_pre.val_loader
    num_updates = num_epochs * len(train_loader)
    
    optimizer = optim.AdamW(model.parameters(), lr=1e-4, weight_decay=0.01, betas=[0.9, 0.999], eps=1e-6)
    lr_scheduler = get_cosine_schedule_with_warmup(optimizer=optimizer, num_warmup_steps=num_updates * 0.1, num_training_steps=num_updates)
    accelerator = Accelerator()
    writer = SummaryWriter("log/" + 'bert')
    
    model, optimizer, lr_scheduler, train_loader, val_loader = accelerator.prepare(model, optimizer, lr_scheduler, train_loader, val_loader)
    accelerator.load_state("./output-0-car")
    
    if replay_layerwise:
        standard_pcas = load_layer_data('layer_pcas.pth')
        standard_pcas = [data.requires_grad_(True) for data in standard_pcas]
        layer_inputs = load_layer_data('layer_inputs.pth')
        layer_labels = load_layer_data('layer_labels.pth')
        layer_attns = load_layer_data('layer_attns.pth')
        print(len(standard_pcas), len(layer_attns))
    
    if replay_decoder:
        decoder_outputs = load_layer_data('decoder_outputs.pth')
        inputs = load_layer_data('inputs.pth')
        labels = load_layer_data('labels.pth')
        attns = load_layer_data('attns.pth')
        print(len(attns))
    
    model.to('cuda')
    
    # freeze decoder
    # for param in model.head.parameters():
    #     param.requires_grad = False
        

    for epoch in range(num_epochs):
        model.train()
        """train origin bert (MLM only)"""
        losses = []
        for i, batch in enumerate(train_loader):   
            # train on new data
            if train_on_newdata:
                loss, _, _ = model(**batch)
                # loss /= 1000000
                losses.append(accelerator.gather(loss.repeat(config.batch_size)))
                
                optimizer.zero_grad()
                accelerator.backward(loss)
                optimizer.step()
                lr_scheduler.step()    
                loss_train = torch.mean(torch.cat(losses)[:len(train_loader.dataset)])            
            
            # replay in former 12 layers
            if replay_layerwise:
                mse_loss = nn.MSELoss()
                batch_old = {'input_ids': layer_inputs[epoch], 'attention_mask': layer_attns[epoch], 'labels': layer_labels[epoch]}
                _, _, layer_outputs = model(**batch_old)
                detached_outputs = [output.detach() for output in layer_outputs]
                detached_outputs = [output.requires_grad_(True) for output in layer_outputs]            
                for j, (detached_output, standard_pca) in enumerate(zip(detached_outputs, standard_pcas)):                
                    if j % 3 == 0:
                        pca_loss = mse_loss(detached_output, standard_pca[epoch * config.batch_size : (epoch+1) * config.batch_size])                      
                        # pca_loss *= 1000000
                        local_optimizer = optim.AdamW(model.bert.layers.layers[j].parameters(), lr=1e-2, weight_decay=0.01, betas=[0.9, 0.999], eps=1e-6)             
                        local_optimizer.zero_grad()
                        pca_loss.backward(retain_graph=True)
                        local_optimizer.step()
                    
            # replay in the decoder layer
            if replay_decoder:                
                device = 'cuda'
                mse_loss = nn.MSELoss()
                batch_old = {'input_ids': inputs[epoch], 'attention_mask': attns[epoch], 'labels': labels[epoch]}
                batch_old = {key: tensor.to(device) for key, tensor in batch.items()}
                decoder_outputs[epoch].to(device)
                _, scores, _ = model(**batch_old)
                scores.to(device)
                print(scores.device, decoder_outputs[epoch].device)
                decoder_loss = mse_loss(scores, decoder_outputs[epoch])
                local_optimizer = optim.AdamW(model.head.parameters(), lr=1e-4, weight_decay=0.01, betas=[0.9, 0.999], eps=1e-6)             
                local_optimizer.zero_grad()
                decoder_loss.backward(retain_graph=True)
                local_optimizer.step()
                
                device = 'cpu'
                batch_old = {key: tensor.to(device) for key, tensor in batch.items()}
                decoder_outputs[epoch].to(device)
                accelerator.print(f'Epoch:{epoch} ({i} Updates)')
                
                
        loss_valid = validate(model, val_loader, accelerator)
        loss_test = validate(model, pre_test_loader, accelerator)
        # accelerator.print(f'Epoch:{epoch} ({i} Updates), Train Loss: {loss_train}, Valid Loss: {loss_valid}, pre_Test Loss: {loss_test}')
        accelerator.print(f'Epoch:{epoch} ({i} Updates),  Valid Loss: {loss_valid}, pre_Test Loss: {loss_test}')

        if accelerator.is_local_main_process:
            # writer.add_scalar('perplexity_train_epoch', loss_train, epoch)
            writer.add_scalar('perplexity_valid', loss_valid, epoch)
            writer.add_scalar('perplexity_test', loss_test, epoch)
            writer.add_scalar('learning_rate', optimizer.param_groups[-1]['lr'], epoch)
        
    accelerator.save_state('./output-formal-2')
    

if __name__ == "__main__":
    set_seed(45)
    
    config = BertConfig.from_json_file('config/bert.json')
    # dataset = RestaurantForLM(config=config)
    dataset = ACLForLM_small(config=config)
    dataset_pre = RestaurantForLM_small(config=config)
    
    model = base_models.BertWithSavers(config=config)
    model.to('cuda')
    # model = base_models.BertWithDecoders(config=config)
    # model = nn.DataParallel(model)
    
    train(model=model, num_epochs=50, dataset=dataset, dataset_pre=dataset_pre)