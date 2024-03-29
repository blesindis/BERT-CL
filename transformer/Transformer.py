import torch
import torch.nn as nn
from einops import rearrange
from transformer.modules.transformer import Embeddings, Attention, FeedForward
    
"""Lora MHSA"""
class LoRAMHSA(nn.Module):
    def __init__(self, config):
        super(LoRAMHSA, self).__init__()
        self.config = config
        self.attention_head_size = int(config.hidden_size / config.num_attention_heads)
        self.num_attention_heads = config.num_attention_heads
        
        self.input_dim = config.hidden_size
        self.lora_dim = 768
        
        """"""
        self.transform_layer = nn.Linear(self.input_dim, self.lora_dim, bias=False) 
            
        self.apply_layers = nn.ModuleList([
            nn.Linear(self.lora_dim, self.attention_head_size*3, bias=False) 
            for _ in range(self.num_attention_heads)
        ])
        """"""
        # self.transform_layers = nn.ModuleList([
        #     nn.Linear(self.input_dim, self.lora_dim, bias=False) 
        #     for _ in range(self.num_attention_heads)
        # ])
        # self.apply_layers = nn.ModuleList([
        #     nn.Linear(self.lora_dim, self.attention_head_size, bias=False) 
        #     for _ in range(self.num_attention_heads)
        # ])
        
        self.scale_factor = self.input_dim ** -0.5  # 1/np.sqrt(dim)
        self.softmax = nn.Softmax(dim=-1)

        # self.head_mask = [1] * self.num_attention_heads
    
    def forward(self, hidden_states: torch.Tensor, attention_mask):        
        transforms = []
        for h in range(self.num_attention_heads):
            # Apply the first transformation
            transformed = self.transform_layer(hidden_states)
            
            # Apply the second transformation and split into Q, K, V
            transformed = self.apply_layers[h](transformed)   
            """"""
            transforms.append(transformed)         
            """"""
            # transforms.append(transformed.repeat(1,1,3))
        transforms = torch.stack(transforms)
        q, k, v = tuple(rearrange(transforms, 'h b n (k d) -> k b h n d', k=3))

        scaled_dot_prod = torch.einsum('... i d , ... j d -> ... i j', q, k) * self.scale_factor
        scaled_dot_prod = scaled_dot_prod.masked_fill(attention_mask[:, None, None, :] == 0, -torch.inf)
        attention = self.softmax(scaled_dot_prod)
        self.attention = attention

        # batch_size, num_head, seq_len, head_dim
        result = torch.einsum('... i j , ... j d -> ... i d', attention, v)
        result = rearrange(result, "b h n d -> b n (h d)")
        return result
    
    
class LoRAAttention(nn.Module):
    def __init__(self, config):
        super(LoRAAttention, self).__init__()
        self.self = LoRAMHSA(config) # split multi-head
        # self.self = SelfAttention(config)
        self.dense = nn.Linear(config.hidden_size, config.hidden_size)
        self.dropout = nn.Dropout(config.hidden_dropout_prob)
        self.LayerNorm = nn.LayerNorm(config.hidden_size, eps=config.layer_norm_eps)

    def forward(self, input_tensor, attention_mask):        
        """Pre Norm No Dropout"""
        # hidden_states = self.LayerNorm(input_tensor)
        # hidden_states = self.self(hidden_states, attention_mask)
        # hidden_states = self.dense(hidden_states)
        # hidden_states = hidden_states + input_tensor
        """Post Norm"""
    def forward(self, input_tensor, attention_mask):        
        """Pre Norm No Dropout"""
        # hidden_states = self.LayerNorm(input_tensor)
        # hidden_states = self.self(hidden_states, attention_mask)
        # hidden_states = self.dense(hidden_states)
        # hidden_states = hidden_states + input_tensor
        """Post Norm"""
        hidden_states = self.self(input_tensor, attention_mask)
        hidden_states = self.dense(hidden_states)
        hidden_states = self.dropout(hidden_states)
        hidden_states = self.LayerNorm(hidden_states + input_tensor)
        return hidden_states
    
    
class TransformerEncoder(nn.Module):
    def __init__(self, config) -> None:
        super(TransformerEncoder, self).__init__()
        self.attention = Attention(config)
        self.ffn = FeedForward(config)
        self.LayerNorm = nn.LayerNorm(config.hidden_size, eps=config.layer_norm_eps)
        self.dropout = nn.Dropout(config.hidden_dropout_prob)

    def forward(self, hidden_states, attention_mask) -> torch.Tensor:
        """Pre Norm No Dropout"""
        # att_output = self.attention(hidden_states, attention_mask)
        # residual = att_output
        # att_output = self.LayerNorm(att_output)
        # ffn_output = self.ffn(att_output)
        # output = residual + ffn_output
        """Post Norm"""
        """Pre Norm No Dropout"""
        # att_output = self.attention(hidden_states, attention_mask)
        # residual = att_output
        # att_output = self.LayerNorm(att_output)
        # ffn_output = self.ffn(att_output)
        # output = residual + ffn_output
        """Post Norm"""
        att_output = self.attention(hidden_states, attention_mask)
        ffn_output = self.ffn(att_output)
        ffn_output = self.dropout(ffn_output)
        output = self.LayerNorm(att_output + ffn_output)
        return output
    
    
class TransformerEncoders(nn.Module):
    def __init__(self, config):
        super(TransformerEncoders, self).__init__()
        self.config = config
        self.layers = nn.ModuleList([TransformerEncoder(config) for _ in range(config.num_hidden_layers)])
    
    def forward(self, hidden_states, attention_mask) -> torch.Tensor:
        for i, layer_module in enumerate(self.layers):
            hidden_states = layer_module(hidden_states, attention_mask)
        return hidden_states
    
    
# tradition bert
# tradition bert
class BertModel(nn.Module):
    def __init__(self, config):
        super(BertModel, self).__init__()
        self.embeddings = Embeddings(config)
        self.encoders = TransformerEncoders(config)
    
    def forward(self, input_ids, attention_mask) -> torch.Tensor:
        embeddings = self.embeddings(input_ids)
        output = self.encoders(embeddings, attention_mask)
        return output


class Experts(nn.Module):
    def __init__(self, config, centers):
        super(Experts, self).__init__()
        self.config = config
        self.experts = nn.ModuleList([TransformerEncoder(config) for _ in range(config.num_experts)])
        self.centers = centers        
        
    def routing(self, hidden_states):
        cluster_list = [[] for _ in range(self.config.num_experts)]
        
        """Sentence"""
        h_pca = hidden_states.mean(dim=1)
        dist = torch.cdist(h_pca.double(), self.centers.double())
        _, min_indices = torch.min(dist, dim=1)
        for i, cluster_index in enumerate(min_indices):
            cluster_list[cluster_index.item()].append(i)
            
        return cluster_list
    
    def forward(self, hidden_states, attention_mask):
        """Sentence"""
        output = hidden_states.new_zeros(hidden_states.shape)
        cluster_list = self.routing(hidden_states)
        for i in range(self.config.num_experts):                        
            output[cluster_list[i], :, :] = self.experts[i](hidden_states[cluster_list[i], :, :], attention_mask[cluster_list[i], :])
        return output


class BertMOE(nn.Module):
    def __init__(self, config, centers):
        super(BertMOE, self).__init__()
        self.layers = nn.ModuleList([Experts(config, centers[i]) for i in range(config.num_hidden_layers)])
        
    def forward(self, hidden_states, attention_mask):
        for i, layer in enumerate(self.layers):
            hidden_states = layer(hidden_states, attention_mask)
        return hidden_states


# Bert with moe
class BertMOEModel(nn.Module):
    def __init__(self, config, centers):
        super(BertMOEModel, self).__init__()
        self.embeddings = Embeddings(config)
        self.layers = BertMOE(config, centers)
        
    def forward(self, input_ids, attention_mask):
        embeddings = self.embeddings(input_ids)
        outputs = self.layers(embeddings, attention_mask)
        return outputs


class SwitchFeedForward(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.n_experts = config.num_experts
        self.capacity_factor = config.capacity_factor
        self.is_scale_prob = True
        self.drop_tokens = False
        self.experts = nn.ModuleList([FeedForward(config) for _ in range(config.num_experts)])
        self.switch = nn.Linear(config.hidden_size, self.n_experts)
        self.softmax = nn.Softmax(dim=-1)

        # self.loss = None
        # self.loss_coef = loss_coef

    # def load_balance_loss(self, counts, route_prob):
    #     total = counts.sum(dim=-1, keepdims=True)
    #     route_frac = counts / total
    #     route_prob = route_prob / total
    #     load_balancing_loss = self.n_experts * (route_frac * route_prob).sum()

    #     return load_balancing_loss

    def forward(self, x: torch.Tensor):
        batch_size, seq_len, d_model = x.shape
        x = x.contiguous().view(-1, d_model)
        final_output = x.new_zeros(x.shape)

        route_prob = self.softmax(self.switch(x))
        route_prob_max, routes = torch.max(route_prob, dim=-1)
        indexes_list = [torch.eq(routes, i).nonzero(as_tuple=True)[0] for i in range(self.n_experts)]      
        
        capacity = int(self.capacity_factor * len(x) / self.n_experts)
        # counts = x.new_tensor([len(indexes_list[i]) for i in range(self.n_experts)])
        # self.loss = self.loss_coef * self.load_balance_loss(counts, route_prob)
        
        dropped = []
        if self.drop_tokens:
            for i in range(self.n_experts):
                if len(indexes_list[i]) > capacity:
                    indexes_list[i] = indexes_list[i][torch.randperm(len(indexes_list[i]))]
                    dropped.append(indexes_list[i][capacity:])
                    indexes_list[i] = indexes_list[i][:capacity]


        expert_output = [self.experts[i](x[indexes_list[i], :]) for i in range(self.n_experts)]
        for i in range(self.n_experts):
            final_output[indexes_list[i], :] = expert_output[i]
            
        if dropped:
            dropped = torch.cat(dropped)
            final_output[dropped, :] = x[dropped, :]


        final_output = final_output * route_prob_max.view(-1, 1) if self.is_scale_prob else final_output * (route_prob_max / route_prob_max.detach()).view(-1, 1)
        final_output = final_output.view(batch_size, seq_len, d_model)

        return final_output
    
    
class SwitchEncoder(nn.Module):
    def __init__(self, config):
        super(SwitchEncoder, self).__init__()
        self.attention = Attention(config)
        self.ffn = SwitchFeedForward(config)
        self.LayerNorm = nn.LayerNorm(config.hidden_size, eps=config.layer_norm_eps)
        self.dropout = nn.Dropout(config.hidden_dropout_prob)
        
    def forward(self, hidden_states, attention_mask):
        """Pre Norm"""
        # att_output = self.attention(hidden_states, attention_mask)
        # residual = att_output
        # att_output = self.LayerNorm(att_output)
        # ffn_output = self.ffn(att_output)
        # # ffn_output = self.dropout(ffn_output)
        
        # # output = self.LayerNorm(att_output + ffn_output)
        # output = residual + ffn_output
        """Post Norm"""
        att_output = self.attention(hidden_states, attention_mask)
        ffn_output = self.ffn(att_output)
        ffn_output = self.dropout(ffn_output)
        output = self.LayerNorm(att_output + ffn_output)        
        
        return output
    
    
class SwitchLayers(nn.Module):
    def __init__(self, config):
        super(SwitchLayers, self).__init__()
        self.layers = nn.ModuleList([SwitchEncoder(config) for _ in range(config.num_hidden_layers)])
        
    def forward(self, hidden_states, attention_mask):
        for i, layer in enumerate(self.layers):
            hidden_states = layer(hidden_states, attention_mask)
        return hidden_states
    
    
class SwitchBertModel(nn.Module):
    def __init__(self, config):
        super(SwitchBertModel, self).__init__()
        self.embeddings = Embeddings(config)
        self.layers = SwitchLayers(config)
        
    def forward(self, input_ids, attention_mask):
        embeddings = self.embeddings(input_ids)
        outputs = self.layers(embeddings, attention_mask)
        return outputs