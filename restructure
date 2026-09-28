we need to edit this pipeline so we have the following 

all the components packed into a docker compose

please delete searxng, crawl4ai and zotero and mineru from here 
our starting point is a folder with a bunch of pdf and references (enote of bib)



inputs:
- research hyphotesis (json)
- keywords (json)
- style (previous paper written by author)
- folder mounted with pdfs and bib or endnote




llm engine:

vllm instace: we connect to an instace this is previously set up we just use it

[
{
"name": "llmlite",
"vendor": "customendpoint",
"apiType": "chat-completions",
"apiKey": "${input:chat.lm.secret.-6d2e0028}",
"models": [
{
"id": "ornl-qwen3-8-27b",
"name": "ORNL Qwen3.8 27B (vLLM)",
"url": "https://75e4-160-36-103-252.ngrok-free.app/v1/chat/completions",
"toolCalling": true,
"vision": true,
"maxInputTokens": 32000,
"maxOutputTokens": 8000
}
]
}
]


THis is what how we should connect to it:



llm agents:

- Convert this into  MCP agents:

/home/jose/Jose_LLM_OCR_PDF_Parser/run_pipeline.sh

1) please make sure we utilize a graph node based chain of thought

2) so ideas keep comparing validating keep delving into the point so we have a graph based reasoning (a GRAPH_DEPTH=) will set how deep we go in each of the nodes


3) we need to use comfy ui this has to be part of the docker compose to grab some of the nodes
 base on a fix parameter prob (PAPER_IMAGE_COUNT) we can generate an images based on the idea that is being developed and go back to that paper and take as reference its own images that is within the paper we used on that graph node



all dockers should be set with a single docker compose