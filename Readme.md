# scripts

## flow by Jose
```
chmod -R 777 /home/recoil/shared_space/parserBibliographyJT/mineru

docker run -it --rm \
  --gpus=all \
  -v /home/recoil/shared_space/parserBibliographyJT/mineru/input_images:/workspace/input_images \
  -v /home/recoil/shared_space/parserBibliographyJT/mineru/output_images:/workspace/output_images \
  mineru_ilab:0.2

magic-pdf -p {some_pdf} -o {some_output_dir} -m auto

magic-pdf -p /workspace/input_images/2008_Winebrake_AssessingEnergyEnvironmental  and Economic Tradeoffs in Intermodal Freight Transportation.pdf -o /workspace/output_images/ -m auto

magic-pdf -p /workspace/input_images/2008_Winebrake_AssessingEnergyEnvironmental  and Economic Tradeoffs in Intermodal Freight Transportation.pdf -o /workspace/output_images/ -m auto


magic-pdf -p /workspace/input_images/'NCCN Breast Cancer Guidelines 6.2024 Nov.11,2024.pdf' -o /workspace/output_images/ -m auto

```

### New Insrtructions

```


docker build -t paper_query:1.0 .

sudo docker rm mineru_new2


sudo docker run -dit \
    --name mineru_new2 \
    --gpus=all \
    --privileged \
    -v /home/recoil/shared_space/parserBibliographyJT/mineru/input_images:/workspace/input_images \
    -v /home/recoil/shared_space/parserBibliographyJT/mineru/output_images:/workspace/output_images \
    -v /home/recoil/shared_space/parserBibliographyJT/mineru/front_ui:/workspace/front_ui \
    --entrypoint "/bin/bash" \
    paper_query:1.0



be654e7a4f2ef9b51119d3fd3e864391094c01f2505f04642e5937d765566bd9

docker exec -it be654e7a4f2ef9b51119d3fd3e864391094c01f2505f04642e5937d765566bd9 /bin/bash


ollama serve &

```
After running this, it should start the server and return you to the shell prompt.
Verify if the server started:
After starting the server, check again if it's running:

```
ps aux | grep ollama
```

You should now see a running ollama process in the output.
Run the model:
Once the ollama server is running, you should be able to execute:
```
ollama run llama3.3

exit
```

```
ollama serve & ollama pull llama3.3 & ollama pull nomic-embed-text

apt-get update && apt-get install -y vim

pip -qq install langchain
pip -qq install langchain-core
pip -qq install langchain-community

!pip install ollama langchain beautifulsoup4 chromadb gradio -q

ps aux | grep ollama

kill -9 <llama process pid>

<!-- !pip install ollama langchain beautifulsoup4 chromadb gradio -q -->

pip install pillow install ollama langchain  chromadb gradio -q

python3 file.py

```


## test-run flow by Dr. Li

- docker build -t <image-name>:<tag> <path-to-dockerfile-directory>

    - docker build -t ilabutk/mineru_ilab:0.1 -f Dockerfile .
    - docker push ilabutk/mineru_ilab:0.1
- test run
    - chmod -R 777 /home/recoil/shared_space/parserBibliographyJT/mineru_xl

    - 
      ```
          docker run -it --rm \
          --gpus=all \
          -v /home/recoil/shared_space/parserBibliographyJT/mineru_xl/input:/workspace/input_images \
          -v /home/recoil/shared_space/parserBibliographyJT/mineru_xl/output:/workspace/output_images \
          ilabutk/mineru_ilab:0.1
    
      ```
     >
     > magic-pdf -p /workspace/input_images/2024_Zhang_SparrowSearchAlgorithmMMT.pdf -o /workspace/output_images/ -m auto
     > :tada:
     >
