from torch.utils.data import DataLoader
from torchvision import transforms
import torchvision
import multiprocessing
from transformers import BertConfig, AutoTokenizer, DataCollatorForLanguageModeling
from datasets import DatasetDict, Dataset, load_dataset, concatenate_datasets, load_from_disk
import os
from collections import Counter
from itertools import chain
import torch
import numpy as np
import sys
import json


class Cifar10():
    def __init__(self, config=None) -> None:
        transform_argumented = transforms.Compose([
            transforms.RandomCrop(32, padding=4),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
        ])

        transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
        ])

        self.batch_size = 64
        self.num_classes = 10

        train_dataset = torchvision.datasets.CIFAR10('datasets/cifar10', train=True, download=True, transform=transform_argumented)
        self.train_loader = DataLoader(train_dataset, batch_size=self.batch_size, shuffle=True)
        test_dataset = torchvision.datasets.CIFAR10('datasets/cifar10', train=False, download=True, transform=transform)
        self.test_loader = DataLoader(test_dataset, batch_size=self.batch_size, shuffle=False)

class Cifar100():
    def __init__(self, config=None) -> None:
        train_transform = transforms.Compose([
            transforms.RandomCrop(32, padding=4),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            transforms.Normalize((0.5071, 0.4867, 0.4408), (0.2675, 0.2565, 0.2761)),
        ])

        test_transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize((0.5071, 0.4867, 0.4408), (0.2675, 0.2565, 0.2761)),
        ])

        self.batch_size = 64
        self.num_classes = 100

        train_dataset = torchvision.datasets.CIFAR100('datasets/cifar100', train=True, download=True, transform=train_transform)
        self.train_loader = DataLoader(train_dataset, batch_size=self.batch_size, shuffle=True)
        test_dataset = torchvision.datasets.CIFAR100('datasets/cifar100', train=False, download=True, transform=test_transform)
        self.test_loader = DataLoader(test_dataset, batch_size=self.batch_size, shuffle=False)

class Mnist():
    def __init__(self, config=None) -> None:
        transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize((0.1307,), (0.3081,))
        ])

        self.batch_size = 256
        self.num_classes = 10

        train_dataset = torchvision.datasets.MNIST('datasets/mnist', train=True, download=True, transform=transform)
        self.train_loader = DataLoader(train_dataset, batch_size=self.batch_size, shuffle=True)
        test_dataset = torchvision.datasets.MNIST('datasets/mnist', train=False, download=True, transform=transform)
        self.test_loader = DataLoader(test_dataset, batch_size=self.batch_size, shuffle=False)


class Wikitext():
    def group_texts(self, examples):
        block_size = self.block_size

        # Concatenate all texts.
        concatenated_examples = {k: sum(examples[k], []) for k in examples.keys()}
        total_length = len(concatenated_examples[list(examples.keys())[0]])
        # We drop the small remainder, we could add padding if the model supported it instead of this drop, you can
            # customize this part to your needs.
        total_length = (total_length // block_size) * block_size
        # Split by chunks of max_len.
        result = {
            k: [t[i : i + block_size] for i in range(0, total_length, block_size)]
            for k, t in concatenated_examples.items()
        }
        result["labels"] = result["input_ids"].copy()
        return result
    
    def preprocess(self, config, path):
        num_proc = multiprocessing.cpu_count() // 2

        raw_datasets = load_from_disk('/home/mychen/ER_TextSpeech/BERT/data/datasets/wikitext-2-raw')
        tokenized_datasets = raw_datasets.map(lambda dataset: self.tokenizer(dataset['text']), batched=True, num_proc=num_proc, remove_columns=["text"])
        lm_dataset = tokenized_datasets.map(self.group_texts, batched=True)
        lm_dataset.save_to_disk(path)
        return lm_dataset

    def __init__(self, config):
        self.block_size = config.seq_len
        self.batch_size = config.batch_size
        self.tokenizer = AutoTokenizer.from_pretrained('/home/mychen/ER_TextSpeech/BERT/model/tokenizer/roberta-base')

        path = os.path.join(config.dataset_cache[config.dataset_name], str(self.block_size))
        if not config.preprocessed:
            self.preprocess(config, path)
        lm_datasets = load_from_disk(path)
        
        data_collator = DataCollatorForLanguageModeling(tokenizer=self.tokenizer, mlm_probability=0.15)
        # data_collator = DistributedSampler(data_collator)
        self.train_loader = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=True, collate_fn=data_collator)
        self.train_loader_unshuffle = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        self.val_loader = DataLoader(lm_datasets['validation'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        self.test_loader = DataLoader(lm_datasets['test'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
    

class IMDB():
    def group_texts(self, examples):
        block_size = self.block_size
        # Concatenate all texts.
        concatenated_examples = {k: sum(examples[k], []) for k in examples.keys() if k != 'label'}
        total_length = len(concatenated_examples[list(examples.keys())[1]])
        total_length = (total_length // block_size) * block_size
        # Split by chunks of max_len.
        result = {
            k: [t[i : i + block_size] for i in range(0, total_length, block_size)]
            for k, t in concatenated_examples.items()
        }
        result["labels"] = result["input_ids"].copy()
        return result

    def __init__(self, config) -> None:
        self.block_size = config.seq_len
        self.tokenizer = AutoTokenizer.from_pretrained('roberta-base')
        self.batch_size = config.batch_size

        raw_datasets = load_dataset('imdb')
        tokenized_datasets = raw_datasets.map(lambda dataset: self.tokenizer(dataset['text'], padding='max_length', truncation=True), batched=True, num_proc=16, remove_columns=["text"])

        path = os.path.join(config.dataset_cache[config.dataset_name], str(self.block_size))
        if not config.preprocessed:
            lm_datasets = tokenized_datasets.map(self.group_texts, batched=True, remove_columns=['label'])
            lm_datasets.save_to_disk(path)
        lm_datasets = load_from_disk(path)
        data_collator = DataCollatorForLanguageModeling(tokenizer=self.tokenizer, mlm_probability=0.15)
        self.lm_train_loader = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=True, collate_fn=data_collator)
        self.lm_val_loader = DataLoader(lm_datasets['test'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)

        self.train_loader = DataLoader(tokenized_datasets['train'], batch_size=self.batch_size, shuffle=True)
        self.test_loader = DataLoader(tokenized_datasets['test'], batch_size=self.batch_size, shuffle=False)
        pass

class AGNews():
    def group_texts(self, examples):
        block_size = self.block_size
        # Concatenate all texts.
        concatenated_examples = {k: sum(examples[k], []) for k in examples.keys() if k != 'label'}
        total_length = len(concatenated_examples[list(examples.keys())[1]])
        total_length = (total_length // block_size) * block_size
        # Split by chunks of max_len.
        result = {
            k: [t[i : i + block_size] for i in range(0, total_length, block_size)]
            for k, t in concatenated_examples.items()
        }
        result["labels"] = result["input_ids"].copy()
        return result

    def lt_dataset(self, tokenized_datasets, tokenizer, ratio=.3):
        all_ids = [sample['input_ids'] for sample in tokenized_datasets['train']]
        concat_ids = list(chain(*all_ids))
        freqs = Counter(concat_ids)

        train_freq = []
        for sample in tokenized_datasets['train']:
            freq = [freqs[w] for w in sample['input_ids'] if w not in tokenizer.all_special_ids]
            train_freq.append(sum(freq) / len(freq))
        _, tail_indices = torch.topk(torch.tensor(train_freq), k=int(ratio*len(train_freq)), largest=False)
        lt_train = Dataset.from_dict(tokenized_datasets['train'][tail_indices])
        lt_train.set_format("torch")
        
        test_freq = []
        for sample in tokenized_datasets['test']:
            freq = [freqs[w] for w in sample['input_ids'] if w not in tokenizer.all_special_ids]
            test_freq.append(sum(freq) / len(freq))
        _, tail_indices = torch.topk(torch.tensor(test_freq), k=int(ratio*len(test_freq)), largest=False)
        lt_test = Dataset.from_dict(tokenized_datasets['test'][tail_indices])
        lt_test.set_format("torch")

        return lt_train, lt_test

    def __init__(self, config) -> None:
        self.block_size = config.seq_len
        self.tokenizer = AutoTokenizer.from_pretrained('roberta-base')
        self.batch_size = config.batch_size

        path = os.path.join(config.dataset_cache[config.dataset_name])
        if not config.preprocessed:
            raw_datasets = load_dataset('ag_news')
            tokenized_datasets = raw_datasets.map(lambda dataset: self.tokenizer(dataset['text'], padding='max_length', truncation=True), batched=True, num_proc=16, remove_columns=["text"])
            tokenized_datasets.save_to_disk(path)
        else:
            tokenized_datasets = load_from_disk(path)

        # path = os.path.join(config.dataset_cache[config.dataset_name], str(self.block_size))
        # if not config.preprocessed:
        #     lm_datasets = tokenized_datasets.map(self.group_texts, batched=True, remove_columns=['label'])
        #     lm_datasets.save_to_disk(path)
        # lm_datasets = load_from_disk(path)
        # data_collator = DataCollatorForLanguageModeling(tokenizer=self.tokenizer, mlm_probability=0.15)
        # self.lm_train_loader = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=True, collate_fn=data_collator)
        # self.lm_val_loader = DataLoader(lm_datasets['test'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)

        tokenized_datasets.set_format("torch")
        self.train_loader = DataLoader(tokenized_datasets['train'], batch_size=self.batch_size, shuffle=True)
        self.test_loader = DataLoader(tokenized_datasets['test'], batch_size=self.batch_size, shuffle=False)

        # lt_train, lt_test = self.lt_dataset(tokenized_datasets, self.tokenizer)
        # self.lt_train_loader = DataLoader(lt_train, batch_size=self.batch_size, shuffle=True)
        # self.lt_test_loader = DataLoader(lt_test, batch_size=self.batch_size, shuffle=False)
        pass

class Shape3D():
    def __init__(self):
        '''
        tag in {base, vertex, edge, cube}
        '''
        image_path = 'datasets/3DShape/all_image.npy'
        label_path = 'datasets/3DShape/all_label.npy'
        images = np.load(image_path)
        label = np.load(label_path)
        
        self.data = torch.from_numpy(images).permute([0,3,1,2]).float() / 255.0  # N, C, W, H
        self.label = torch.from_numpy(label)
        self.label[:, 0] = self.label[:, 0] / 0.6
        self.label[:, 1] = self.label[:, 1] / 0.6
        self.label[:, 2] = self.label[:, 2] / 0.6
        self.label[:, 3] = (self.label[:, 3]  - 0.75) / 0.25
        self.label[:, 4] = self.label[:, 4] / 2
        self.label[:, 5] = (self.label[:, 5] + 15) / 30
    
    def __len__(self):
        return self.data.shape[0]

    def __getitem__(self, index):
        return self.data[index], self.label[index]


class RestaurantForLM():
    def group_texts(self, examples):

        concatenated_examples = {k: sum(examples[k], []) for k in examples.keys()}
        total_length = len(concatenated_examples[list(examples.keys())[0]])
        # We drop the small remainder, we could add padding if the model supported it instead of this drop, you can
        # customize this part to your needs.
        if total_length >= self.block_size:
            total_length = (total_length // self.block_size) * self.block_size
        # Split by chunks of max_len.
        result = {
            k: [t[i: i + self.block_size] for i in range(0, total_length, self.block_size)]
            for k, t in concatenated_examples.items()
        }
        result["labels"] = result["input_ids"].copy()
        return result
    
    def tokenize_function(self, examples):
        return self.tokenizer(examples[self.text_column_name], return_special_tokens_mask=True)
    
    def preprocess(self, config, path):
        data_files = {'train': '/home/archen/yelp_restaurant.txt'}
        datasets = load_dataset('text', data_files=data_files)
        datasets["validation"] = load_dataset(
            'text', data_files=data_files,split=f"train[:{0.5}%]"
        )
        datasets["train"] = load_dataset(
            'text', data_files=data_files,
            split=f"train[{5}%:]",
        )
        #rawdatasets
        column_names = datasets["train"].column_names
        self.text_column_name = "text" if "text" in column_names else column_names[0]
        tokenized_datasets = datasets.map(
            self.tokenize_function,
            batched=True,
            num_proc=config.preprocessing_num_workers,
            remove_columns=column_names,
            load_from_cache_file=not config.overwrite_cache,
            desc="Running tokenizer on every text in dataset",
        )
        tokenized_datasets = tokenized_datasets.map(
            self.group_texts,
            batched=True,
            num_proc=config.preprocessing_num_workers,
            load_from_cache_file=not config.overwrite_cache,
            desc=f"Grouping texts in chunks of {1024}",
        )
        tokenized_datasets.save_to_disk(path)
        return tokenized_datasets

    def __init__(self, config):
        self.block_size = config.seq_len
        self.batch_size = config.batch_size
        self.tokenizer = AutoTokenizer.from_pretrained('roberta-base')
        path = os.path.join("/home/archen/datasets/restaurantforLM", str(self.block_size))
        if not config.preprocessed:
            self.preprocess(config, path)
        lm_datasets = load_from_disk(path)
        seed = 42
        torch.manual_seed(seed)
        np.random.seed(seed)
        data_collator = DataCollatorForLanguageModeling(tokenizer=self.tokenizer, mlm_probability=0.15)
        self.train_loader = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=True, collate_fn=data_collator)
        self.train_loader_unshuffle = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        self.val_loader = DataLoader(lm_datasets['validation'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        # self.test_loader = DataLoader(lm_datasets['test'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)

class ACLForLM():
    def group_texts(self, examples):

        concatenated_examples = {k: sum(examples[k], []) for k in examples.keys()}
        total_length = len(concatenated_examples[list(examples.keys())[0]])
        # We drop the small remainder, we could add padding if the model supported it instead of this drop, you can
        # customize this part to your needs.
        if total_length >= self.block_size:
            total_length = (total_length // self.block_size) * self.block_size
        # Split by chunks of max_len.
        result = {
            k: [t[i: i + self.block_size] for i in range(0, total_length, self.block_size)]
            for k, t in concatenated_examples.items()
        }
        result["labels"] = result["input_ids"].copy()
        return result
    
    def tokenize_function(self, examples):
        return self.tokenizer(examples[self.text_column_name], return_special_tokens_mask=True)
    
    def preprocess(self, config, path):
        data_files = {'train': '/home/archen/acl_anthology.txt'}
        datasets = load_dataset('text', data_files=data_files)
        datasets["validation"] = load_dataset(
            'text', data_files=data_files,split=f"train[:{0.5}%]"
        )
        datasets["train"] = load_dataset(
            'text', data_files=data_files,
            split=f"train[{5}%:]",
        )
        #rawdatasets
        column_names = datasets["train"].column_names
        self.text_column_name = "text" if "text" in column_names else column_names[0]
        tokenized_datasets = datasets.map(
            self.tokenize_function,
            batched=True,
            num_proc=config.preprocessing_num_workers,
            remove_columns=column_names,
            load_from_cache_file=not config.overwrite_cache,
            desc="Running tokenizer on every text in dataset",
        )
        tokenized_datasets = tokenized_datasets.map(
            self.group_texts,
            batched=True,
            num_proc=config.preprocessing_num_workers,
            load_from_cache_file=not config.overwrite_cache,
            desc=f"Grouping texts in chunks of {1024}",
        )
        tokenized_datasets.save_to_disk(path)
        return tokenized_datasets

    def __init__(self, config):
        self.block_size = config.seq_len
        self.batch_size = config.batch_size
        self.tokenizer = AutoTokenizer.from_pretrained('roberta-base')
        path = os.path.join("/home/archen/datasets/ACLforLM", str(self.block_size))
        if not config.preprocessed:
            self.preprocess(config, path)
        lm_datasets = load_from_disk(path)
        seed = 42
        torch.manual_seed(seed)
        np.random.seed(seed)
        data_collator = DataCollatorForLanguageModeling(tokenizer=self.tokenizer, mlm_probability=0.15)
        self.train_loader = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=True, collate_fn=data_collator)
        self.train_loader_unshuffle = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        self.val_loader = DataLoader(lm_datasets['validation'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        # self.test_loader = DataLoader(lm_datasets['test'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)

class PhoneForLM():
    def group_texts(self, examples):

        concatenated_examples = {k: sum(examples[k], []) for k in examples.keys()}
        total_length = len(concatenated_examples[list(examples.keys())[0]])
        # We drop the small remainder, we could add padding if the model supported it instead of this drop, you can
        # customize this part to your needs.
        if total_length >= self.block_size:
            total_length = (total_length // self.block_size) * self.block_size
        # Split by chunks of max_len.
        result = {
            k: [t[i: i + self.block_size] for i in range(0, total_length, self.block_size)]
            for k, t in concatenated_examples.items()
        }
        result["labels"] = result["input_ids"].copy()
        return result
    
    def tokenize_function(self, examples):
        return self.tokenizer(examples[self.text_column_name], return_special_tokens_mask=True)
    
    def preprocess(self, config, path):
        data_files = {'train': '/home/archen/phone.txt'}
        datasets = load_dataset('text', data_files=data_files)
        datasets["validation"] = load_dataset(
            'text', data_files=data_files,split=f"train[:{5}%]"
        )
        datasets["train"] = load_dataset(
            'text', data_files=data_files,
            split=f"train[{5}%:]",
        )
        #rawdatasets
        column_names = datasets["train"].column_names
        self.text_column_name = "text" if "text" in column_names else column_names[0]
        tokenized_datasets = datasets.map(
            self.tokenize_function,
            batched=True,
            num_proc=config.preprocessing_num_workers,
            remove_columns=column_names,
            load_from_cache_file=not config.overwrite_cache,
            desc="Running tokenizer on every text in dataset",
        )
        tokenized_datasets = tokenized_datasets.map(
            self.group_texts,
            batched=True,
            num_proc=config.preprocessing_num_workers,
            load_from_cache_file=not config.overwrite_cache,
            desc=f"Grouping texts in chunks of {1024}",
        )
        tokenized_datasets.save_to_disk(path)
        return tokenized_datasets

    def __init__(self, config):
        self.block_size = config.seq_len
        self.batch_size = config.batch_size
        self.tokenizer = AutoTokenizer.from_pretrained('roberta-base')

        path = os.path.join("/home/archen/datasets/PhoneforLM", str(self.block_size))
        if not config.preprocessed:
            self.preprocess(config, path)
        lm_datasets = load_from_disk(path)
        seed = 42
        torch.manual_seed(seed)
        np.random.seed(seed)
        data_collator = DataCollatorForLanguageModeling(tokenizer=self.tokenizer, mlm_probability=0.15)
        self.train_loader = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=True, collate_fn=data_collator)
        self.train_loader_unshuffle = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        self.val_loader = DataLoader(lm_datasets['validation'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        # self.test_loader = DataLoader(lm_datasets['test'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)

class CameraForLM():
    def group_texts(self, examples):

        concatenated_examples = {k: sum(examples[k], []) for k in examples.keys()}
        total_length = len(concatenated_examples[list(examples.keys())[0]])
        # We drop the small remainder, we could add padding if the model supported it instead of this drop, you can
        # customize this part to your needs.
        if total_length >= self.block_size:
            total_length = (total_length // self.block_size) * self.block_size
        # Split by chunks of max_len.
        result = {
            k: [t[i: i + self.block_size] for i in range(0, total_length, self.block_size)]
            for k, t in concatenated_examples.items()
        }
        result["labels"] = result["input_ids"].copy()
        return result
    
    def tokenize_function(self, examples):
        return self.tokenizer(examples[self.text_column_name], return_special_tokens_mask=True)
    
    def preprocess(self, config, path):
        data_files = {'train': '/home/archen/camera.txt'}
        datasets = load_dataset('text', data_files=data_files)
        datasets["validation"] = load_dataset(
            'text', data_files=data_files,split=f"train[:{5}%]"
        )
        datasets["train"] = load_dataset(
            'text', data_files=data_files,
            split=f"train[{5}%:]",
        )
        #rawdatasets
        column_names = datasets["train"].column_names
        self.text_column_name = "text" if "text" in column_names else column_names[0]
        tokenized_datasets = datasets.map(
            self.tokenize_function,
            batched=True,
            num_proc=config.preprocessing_num_workers,
            remove_columns=column_names,
            load_from_cache_file=not config.overwrite_cache,
            desc="Running tokenizer on every text in dataset",
        )
        tokenized_datasets = tokenized_datasets.map(
            self.group_texts,
            batched=True,
            num_proc=config.preprocessing_num_workers,
            load_from_cache_file=not config.overwrite_cache,
            desc=f"Grouping texts in chunks of {1024}",
        )
        tokenized_datasets.save_to_disk(path)
        return tokenized_datasets

    def __init__(self, config):
        self.block_size = config.seq_len
        self.batch_size = config.batch_size
        self.tokenizer = AutoTokenizer.from_pretrained('roberta-base')

        path = os.path.join("/home/archen/datasets/CameraforLM", str(self.block_size))
        if not config.preprocessed:
            self.preprocess(config, path)
        lm_datasets = load_from_disk(path)
        seed = 42
        torch.manual_seed(seed)
        np.random.seed(seed)
        data_collator = DataCollatorForLanguageModeling(tokenizer=self.tokenizer, mlm_probability=0.15)
        self.train_loader = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=True, collate_fn=data_collator)
        self.train_loader_unshuffle = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        self.val_loader = DataLoader(lm_datasets['validation'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        # self.test_loader = DataLoader(lm_datasets['test'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)

class PubMedForLM():
    def group_texts(self, examples):

        concatenated_examples = {k: sum(examples[k], []) for k in examples.keys()}
        total_length = len(concatenated_examples[list(examples.keys())[0]])
        # We drop the small remainder, we could add padding if the model supported it instead of this drop, you can
        # customize this part to your needs.
        if total_length >= self.block_size:
            total_length = (total_length // self.block_size) * self.block_size
        # Split by chunks of max_len.
        result = {
            k: [t[i: i + self.block_size] for i in range(0, total_length, self.block_size)]
            for k, t in concatenated_examples.items()
        }
        result["labels"] = result["input_ids"].copy()
        return result
    
    def tokenize_function(self, examples):
        return self.tokenizer(examples[self.text_column_name], return_special_tokens_mask=True)
    
    def preprocess(self, config, path):
        data_files = {'train': '/home/archen/format_pubmed_small.txt'}
        datasets = load_dataset('text', data_files=data_files)
        datasets["validation"] = load_dataset(
            'text', data_files=data_files,split=f"train[:{5}%]"
        )
        datasets["train"] = load_dataset(
            'text', data_files=data_files,
            split=f"train[{5}%:]",
        )
        #rawdatasets
        column_names = datasets["train"].column_names
        self.text_column_name = "text" if "text" in column_names else column_names[0]
        tokenized_datasets = datasets.map(
            self.tokenize_function,
            batched=True,
            num_proc=config.preprocessing_num_workers,
            remove_columns=column_names,
            load_from_cache_file=not config.overwrite_cache,
            desc="Running tokenizer on every text in dataset",
        )
        tokenized_datasets = tokenized_datasets.map(
            self.group_texts,
            batched=True,
            num_proc=config.preprocessing_num_workers,
            load_from_cache_file=not config.overwrite_cache,
            desc=f"Grouping texts in chunks of {1024}",
        )
        tokenized_datasets.save_to_disk(path)
        return tokenized_datasets

    def __init__(self, config):
        self.block_size = config.seq_len
        self.batch_size = config.batch_size
        self.tokenizer = AutoTokenizer.from_pretrained('roberta-base')

        path = os.path.join("/home/archen/datasets/PubMedforLM", str(self.block_size))
        if not config.preprocessed:
            self.preprocess(config, path)
        lm_datasets = load_from_disk(path)
        seed = 42
        torch.manual_seed(seed)
        np.random.seed(seed)
        data_collator = DataCollatorForLanguageModeling(tokenizer=self.tokenizer, mlm_probability=0.15)
        self.train_loader = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=True, collate_fn=data_collator)
        self.train_loader_unshuffle = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        self.val_loader = DataLoader(lm_datasets['validation'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        # self.test_loader = DataLoader(lm_datasets['test'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)

class AIForLM():
    def group_texts(self, examples):

        concatenated_examples = {k: sum(examples[k], []) for k in examples.keys()}
        total_length = len(concatenated_examples[list(examples.keys())[0]])
        # We drop the small remainder, we could add padding if the model supported it instead of this drop, you can
        # customize this part to your needs.
        if total_length >= self.block_size:
            total_length = (total_length // self.block_size) * self.block_size
        # Split by chunks of max_len.
        result = {
            k: [t[i: i + self.block_size] for i in range(0, total_length, self.block_size)]
            for k, t in concatenated_examples.items()
        }
        result["labels"] = result["input_ids"].copy()
        return result
    
    def tokenize_function(self, examples):
        return self.tokenizer(examples[self.text_column_name], return_special_tokens_mask=True)
    
    def preprocess(self, config, path):
        data_files = {'train': '/home/archen/ai_corpus.txt'}
        datasets = load_dataset('text', data_files=data_files)
        datasets["validation"] = load_dataset(
            'text', data_files=data_files,split=f"train[:{5}%]"
        )
        datasets["train"] = load_dataset(
            'text', data_files=data_files,
            split=f"train[{5}%:]",
        )
        #rawdatasets
        column_names = datasets["train"].column_names
        self.text_column_name = "text" if "text" in column_names else column_names[0]
        tokenized_datasets = datasets.map(
            self.tokenize_function,
            batched=True,
            num_proc=config.preprocessing_num_workers,
            remove_columns=column_names,
            load_from_cache_file=not config.overwrite_cache,
            desc="Running tokenizer on every text in dataset",
        )
        tokenized_datasets = tokenized_datasets.map(
            self.group_texts,
            batched=True,
            num_proc=config.preprocessing_num_workers,
            load_from_cache_file=not config.overwrite_cache,
            desc=f"Grouping texts in chunks of {1024}",
        )
        tokenized_datasets.save_to_disk(path)
        return tokenized_datasets

    def __init__(self, config):
        self.block_size = config.seq_len
        self.batch_size = config.batch_size
        self.tokenizer = AutoTokenizer.from_pretrained('roberta-base')

        path = os.path.join("/home/archen/datasets/AIforLM", str(self.block_size))
        if not config.preprocessed:
            self.preprocess(config, path)
        lm_datasets = load_from_disk(path)
        seed = 42
        torch.manual_seed(seed)
        np.random.seed(seed)
        data_collator = DataCollatorForLanguageModeling(tokenizer=self.tokenizer, mlm_probability=0.15)
        self.train_loader = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=True, collate_fn=data_collator)
        self.train_loader_unshuffle = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        self.val_loader = DataLoader(lm_datasets['validation'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        # self.test_loader = DataLoader(lm_datasets['test'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)

class MixedData():
    def __init__(self, config):
        self.block_size = config.seq_len
        self.batch_size = config.batch_size
        self.tokenizer = AutoTokenizer.from_pretrained('roberta-base')
        # path1 = os.path.join("/home/archen/datasets/ACLforLM", str(self.block_size))
        path1 = os.path.join("/home/archen/datasets/PhoneforLM", str(self.block_size))
        path2 = os.path.join("/home/archen/datasets/restaurantforLM", str(self.block_size))
        path3 = os.path.join("/home/archen/datasets/CameraforLM", str(self.block_size))
        lm_datasets1 = load_from_disk(path1)
        lm_datasets2 = load_from_disk(path2)
        lm_datasets3 = load_from_disk(path3)
        print(len(lm_datasets1), len(lm_datasets2), len(lm_datasets3))
        lm_datasets = torch.utils.data.ConcatDataset([lm_datasets1['train'], lm_datasets2['train'], lm_datasets3['train']])
        
        seed = 42
        torch.manual_seed(seed)
        np.random.seed(seed)
        data_collator = DataCollatorForLanguageModeling(tokenizer=self.tokenizer, mlm_probability=0.15)
        self.train_loader = DataLoader(lm_datasets, batch_size=self.batch_size, shuffle=True, collate_fn=data_collator)
        # self.train_loader_unshuffle = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        # self.val_loader = DataLoader(lm_datasets['validation'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)

class Eval_Data1():
    def __init__(self, config):
        self.block_size = config.seq_len
        self.batch_size = config.batch_size
        self.tokenizer = AutoTokenizer.from_pretrained('roberta-base')
        path1 = os.path.join("/home/archen/datasets/restaurantforLM", str(self.block_size))
        path2 = os.path.join("/home/archen/datasets/ACLforLM", str(self.block_size))
        lm_datasets1 = load_from_disk(path1)
        lm_datasets2 = load_from_disk(path2)
        
        lm_datasets1 = torch.utils.data.Subset(lm_datasets1['train'], range(100))
        lm_datasets2 = torch.utils.data.Subset(lm_datasets2['train'], range(100))
        lm_datasets = torch.utils.data.ConcatDataset([lm_datasets1, lm_datasets2])
        seed = 42
        torch.manual_seed(seed)
        np.random.seed(seed)
        data_collator = DataCollatorForLanguageModeling(tokenizer=self.tokenizer, mlm_probability=0.15)
        self.train_loader1 = DataLoader(lm_datasets1, batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        self.train_loader2 = DataLoader(lm_datasets2, batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        self.mixed_loader = DataLoader(lm_datasets, batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)

class Eval_Data2():
    def __init__(self, config):
        self.block_size = config.seq_len
        self.batch_size = config.batch_size
        self.tokenizer = AutoTokenizer.from_pretrained('roberta-base')
        # path1 = os.path.join("/home/archen/datasets/ACLforLM", str(self.block_size))

        path1 = os.path.join("/home/archen/datasets/PhoneforLM", str(self.block_size))
        path2 = os.path.join("/home/archen/datasets/restaurantforLM", str(self.block_size))
        path3 = os.path.join("/home/archen/datasets/CameraforLM", str(self.block_size))
        lm_datasets1 = load_from_disk(path1)
        lm_datasets2 = load_from_disk(path2)
        lm_datasets3 = load_from_disk(path3)
        print(len(lm_datasets1['train']), len(lm_datasets2['train']), len(lm_datasets3['train']))

        # path2 = os.path.join("/home/archen/datasets/restaurantforLM", str(self.block_size))
        # lm_datasets1 = load_from_disk(path1)
        # lm_datasets2 = load_from_disk(path2)
        lm_datasets1 = torch.utils.data.Subset(lm_datasets1['train'], range(3000))
        lm_datasets2 = torch.utils.data.Subset(lm_datasets2['train'], range(3000))
        lm_datasets3 = torch.utils.data.Subset(lm_datasets3['train'], range(3000))
        seed = 42
        torch.manual_seed(seed)
        np.random.seed(seed)
        data_collator = DataCollatorForLanguageModeling(tokenizer=self.tokenizer, mlm_probability=0.15)
        self.train_loader1 = DataLoader(lm_datasets1, batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        self.train_loader2 = DataLoader(lm_datasets2, batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        self.train_loader3 = DataLoader(lm_datasets3, batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)

class RestaurantForLM_small():
    def group_texts(self, examples):

        concatenated_examples = {k: sum(examples[k], []) for k in examples.keys()}
        total_length = len(concatenated_examples[list(examples.keys())[0]])
        # We drop the small remainder, we could add padding if the model supported it instead of this drop, you can
        # customize this part to your needs.
        if total_length >= self.block_size:
            total_length = (total_length // self.block_size) * self.block_size
        # Split by chunks of max_len.
        result = {
            k: [t[i: i + self.block_size] for i in range(0, total_length, self.block_size)]
            for k, t in concatenated_examples.items()
        }
        result["labels"] = result["input_ids"].copy()
        return result
    
    def tokenize_function(self, examples):
        return self.tokenizer(examples[self.text_column_name], return_special_tokens_mask=True)
    
    def preprocess(self, config, path):
        data_files = {'train': '/home/mychen/ER_TextSpeech/BERT/data/datasets/restaurant/yelp_restaurant.txt'}
        datasets = load_dataset('text', data_files=data_files)
        datasets["validation"] = load_dataset(
            'text', data_files=data_files,split="train[:1%]"
        )
        datasets["train"] = load_dataset(
            'text', data_files=data_files,
            split="train[5%:]",
        )
        #rawdatasets
        column_names = datasets["train"].column_names
        self.text_column_name = "text" if "text" in column_names else column_names[0]
        tokenized_datasets = datasets.map(
            self.tokenize_function,
            batched=True,
            # num_proc=config.preprocessing_num_workers,
            remove_columns=column_names,
            # load_from_cache_file=not config.overwrite_cache,
            desc="Running tokenizer on every text in dataset",
        )
        tokenized_datasets = tokenized_datasets.map(
            self.group_texts,
            batched=True,
            # num_proc=config.preprocessing_num_workers,
            # load_from_cache_file=not config.overwrite_cache,
            desc=f"Grouping texts in chunks of {1024}",
        )
        tokenized_datasets.save_to_disk(path)
        return tokenized_datasets

    def __init__(self, config):
        self.block_size = config.seq_len
        self.batch_size = config.batch_size
        self.tokenizer = AutoTokenizer.from_pretrained('/home/mychen/ER_TextSpeech/BERT/model/tokenizer/roberta-base')
        path = os.path.join("/home/mychen/ER_TextSpeech/BERT/data/datasets/tokenized/restaurant", str(self.block_size))
        if not config.preprocessed:
            self.preprocess(config, path)
        lm_datasets = load_from_disk(path)
        lm_datasets_train = torch.utils.data.Subset(lm_datasets['train'], range(19200))
        lm_datasets_val = torch.utils.data.Subset(lm_datasets['validation'], range(1920))
        seed = 42
        torch.manual_seed(seed)
        np.random.seed(seed)
        data_collator = DataCollatorForLanguageModeling(tokenizer=self.tokenizer, mlm_probability=0.15)
        self.train_loader = DataLoader(lm_datasets_train, batch_size=self.batch_size, shuffle=True, collate_fn=data_collator)
        self.train_loader_unshuffle = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        self.val_loader = DataLoader(lm_datasets_val, batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        # self.test_loader = DataLoader(lm_datasets['test'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)

class ACLForLM_small():
    def group_texts(self, examples):

        concatenated_examples = {k: sum(examples[k], []) for k in examples.keys()}
        total_length = len(concatenated_examples[list(examples.keys())[0]])
        # We drop the small remainder, we could add padding if the model supported it instead of this drop, you can
        # customize this part to your needs.
        if total_length >= self.block_size:
            total_length = (total_length // self.block_size) * self.block_size
        # Split by chunks of max_len.
        result = {
            k: [t[i: i + self.block_size] for i in range(0, total_length, self.block_size)]
            for k, t in concatenated_examples.items()
        }
        result["labels"] = result["input_ids"].copy()
        return result
    
    def tokenize_function(self, examples):
        return self.tokenizer(examples[self.text_column_name], return_special_tokens_mask=True)
    
    def preprocess(self, config, path):
        data_files = {'train': '/home/mychen/ER_TextSpeech/BERT/data/datasets/acl/acl_anthology.txt'}
        datasets = load_dataset('text', data_files=data_files)
        datasets["validation"] = load_dataset(
            'text', data_files=data_files,split="train[:1%]"
        )
        datasets["train"] = load_dataset(
            'text', data_files=data_files,
            split="train[5%:]",
        )
        #rawdatasets
        column_names = datasets["train"].column_names
        self.text_column_name = "text" if "text" in column_names else column_names[0]
        tokenized_datasets = datasets.map(
            self.tokenize_function,
            batched=True,
            # num_proc=config.preprocessing_num_workers,
            remove_columns=column_names,
            # load_from_cache_file=not config.overwrite_cache,
            desc="Running tokenizer on every text in dataset",
        )
        tokenized_datasets = tokenized_datasets.map(
            self.group_texts,
            batched=True,
            # num_proc=config.preprocessing_num_workers,
            # load_from_cache_file=not config.overwrite_cache,
            desc=f"Grouping texts in chunks of {1024}",
        )
        tokenized_datasets.save_to_disk(path)
        return tokenized_datasets

    def __init__(self, config):
        self.block_size = config.seq_len
        self.batch_size = config.batch_size
        self.tokenizer = AutoTokenizer.from_pretrained('/home/mychen/ER_TextSpeech/BERT/model/tokenizer/roberta-base')
        path = os.path.join("/home/mychen/ER_TextSpeech/BERT/data/datasets/tokenized/acl", str(self.block_size))
        if not config.preprocessed:
            self.preprocess(config, path)
        lm_datasets = load_from_disk(path)
        lm_datasets_train = torch.utils.data.Subset(lm_datasets['train'], range(19200))
        lm_datasets_val = torch.utils.data.Subset(lm_datasets['validation'], range(1920))
        seed = 42
        torch.manual_seed(seed)
        np.random.seed(seed)
        data_collator = DataCollatorForLanguageModeling(tokenizer=self.tokenizer, mlm_probability=0.15)
        self.train_loader = DataLoader(lm_datasets_train, batch_size=self.batch_size, shuffle=True, collate_fn=data_collator)
        self.train_loader_unshuffle = DataLoader(lm_datasets['train'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        self.val_loader = DataLoader(lm_datasets_val, batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)
        # self.test_loader = DataLoader(lm_datasets['test'], batch_size=self.batch_size, shuffle=False, collate_fn=data_collator)


if __name__ == "__main__":
    config = BertConfig.from_json_file('/home/archen/cl/config/bert_small_sp.json')
    
    dataset = CameraForLM(config)