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

magic-pdf -p /workspace/input_images/'NCCN Breast Cancer Guidelines 6.2024 Nov.11,2024.pdf' -o /workspace/output_images/ -m auto

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
