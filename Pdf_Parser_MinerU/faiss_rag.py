#
# pip install transformers faiss-cpu
#
""" # script log ofr conda env setup
conda update conda
conda update anaconda

conda remove backports
conda install backports

conda create -n faiss_rag_env python=3.8
conda activate faiss_rag_env
conda install pytorch torchvision torchaudio -c pytorch
pip install transformers faiss-cpu

python faiss_rag.py
"""
import json
import faiss
import numpy as np
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, pipeline

# Load the JSON file
with open('/Users/xli/Documents/GitHub/Jose_LLM_OCR_PDF_Parser/Pdf_Parser_MinerU/use_cases/my_pubs/results/CAIE_Drones_2023/auto/CAIE_Drones_2023_content_list.json', 'r') as f:
    data = json.load(f)

# Extract text and page_idx
texts = [item['text'] for item in data if 'text' in item]
page_idxs = [item['page_idx'] for item in data if 'text' in item]

# Tokenize the texts
tokenizer = AutoTokenizer.from_pretrained("facebook/bart-large")
model = AutoModelForSeq2SeqLM.from_pretrained("facebook/bart-large")

# Encode the texts
encoded_texts = [tokenizer.encode(text, return_tensors='pt', truncation=True, max_length=512) for text in texts]

# Create a FAISS index
d = 1024  # Dimension of the embeddings (BART model has 1024-dimensional embeddings)
index = faiss.IndexFlatL2(d)

# Compute embeddings and add to the index
embeddings = []
for encoded_text in encoded_texts:
    with torch.no_grad():
        output = model.get_encoder()(encoded_text)[0].mean(dim=1).numpy()
        embeddings.append(output)
        index.add(output)

# Function to search the index
def search(query, k=5):
    query_embedding = model.get_encoder()(tokenizer.encode(query, return_tensors='pt', truncation=True, max_length=512))[0].mean(dim=1).detach().numpy()
    D, I = index.search(query_embedding, k)
    results = [(texts[i], page_idxs[i]) for i in I[0]]
    return results

# Function to generate an answer
def generate_answer(query):
    search_results = search(query)
    context = " ".join([result[0] for result in search_results])
    input_text = f"question: {query} context: {context}"
    input_ids = tokenizer.encode(input_text, return_tensors='pt', truncation=True, max_length=512)
    output_ids = model.generate(input_ids, max_length=150)
    answer = tokenizer.decode(output_ids[0], skip_special_tokens=True)
    return answer

# Example usage
query = "What is the main contribution of the study?"
answer = generate_answer(query)
print(answer)