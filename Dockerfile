# Use the official Ubuntu base image
FROM ubuntu:22.04

# Set environment variables to non-interactive to avoid prompts during installation
ENV DEBIAN_FRONTEND=noninteractive
ENV container docker

# Install systemd and other necessary packages
RUN apt-get update && \
    apt-get install -y \
        systemd \
        curl \
        software-properties-common \
        pciutils \
        lshw \
        ssh \
        python3.10 \
        python3.10-venv \
        python3.10-distutils \
        python3-pip \
        wget \
        git \
        libgl1 \
        libglib2.0-0 && \
    apt-get clean

# VOLUME for systemd to work properly
VOLUME ["/sys/fs/cgroup"]

# Install additional dependencies and set up Python environment
RUN add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y python3.10 && \
    rm -rf /var/lib/apt/lists/*

# Set Python 3.10 as the default python3
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1

# Create a virtual environment for MinerU
RUN python3 -m venv /opt/mineru_venv

# Activate the virtual environment and install necessary Python packages
RUN /bin/bash -c "source /opt/mineru_venv/bin/activate && \
    pip3 install --upgrade pip && \
    wget https://github.com/opendatalab/MinerU/raw/master/docker/global/requirements.txt -O requirements.txt && \
    pip3 install -r requirements.txt --extra-index-url https://wheels.myhloli.com && \
    pip3 install paddlepaddle-gpu==3.0.0b1 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/"

# Copy the configuration file template and install magic-pdf latest
RUN /bin/bash -c "wget https://github.com/opendatalab/MinerU/raw/master/magic-pdf.template.json && \
    cp magic-pdf.template.json /root/magic-pdf.json && \
    source /opt/mineru_venv/bin/activate && \
    pip3 install -U magic-pdf"

# Download models and update the configuration file
RUN /bin/bash -c "pip3 install huggingface_hub && \
    wget https://github.com/opendatalab/MinerU/raw/master/scripts/download_models_hf.py -O download_models.py && \
    python3 download_models.py && \
    sed -i 's|cpu|cuda|g' /root/magic-pdf.json"

# Append virtual environment activation to .bashrc
RUN echo "source /opt/mineru_venv/bin/activate" >> ~/.bashrc

# Set the working directory
WORKDIR /workspace

# Create directories for input and output images
RUN mkdir -p /workspace/input_images /workspace/output_images && \
    chmod -R 777 /workspace

# Create and set up the front_ui folder
RUN mkdir -p /workspace/front_ui && \
    chmod -R 777 /workspace/front_ui

# Install Ollama, LangChain, and other required Python packages
RUN /bin/bash -c "pip install -qq ollama langchain langchain-core langchain-community beautifulsoup4 chromadb gradio"

# Set the entry point for persistent interactive shell
ENTRYPOINT ["/bin/bash"]

# Set default command to run systemd and Ollama services
CMD ["/bin/bash", "-c", "ollama serve & ollama pull llama3 & ollama pull nomic-embed-text & /lib/systemd/systemd"]





# # Use the official Ubuntu base image
# FROM ubuntu:22.04

# # Set environment variables to non-interactive to avoid prompts during installation
# ENV DEBIAN_FRONTEND=noninteractive

# ENV container docker

# RUN apt-get update && \
#     apt-get install -y systemd && \
#     apt-get clean

# VOLUME [ "/sys/fs/cgroup" ]

# CMD ["/lib/systemd/systemd"]


# # Update the package list and install necessary packages
# RUN apt-get update && \
#     apt-get install -y \
#         software-properties-common && \
#     add-apt-repository ppa:deadsnakes/ppa && \
#     apt-get update && \
#     apt-get install -y \
#         python3.10 \
#         python3.10-venv \
#         python3.10-distutils \
#         python3-pip \
#         wget \
#         git \
#         libgl1 \
#         libglib2.0-0 \
#         && rm -rf /var/lib/apt/lists/*

# # Set Python 3.10 as the default python3
# RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1

# # Create a virtual environment for MinerU
# RUN python3 -m venv /opt/mineru_venv

# # Activate the virtual environment and install necessary Python packages
# RUN /bin/bash -c "source /opt/mineru_venv/bin/activate && \
#     pip3 install --upgrade pip && \
#     wget https://github.com/opendatalab/MinerU/raw/master/docker/global/requirements.txt -O requirements.txt && \
#     pip3 install -r requirements.txt --extra-index-url https://wheels.myhloli.com && \
#     pip3 install paddlepaddle-gpu==3.0.0b1 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/"

# # Copy the configuration file template and install magic-pdf latest
# RUN /bin/bash -c "wget https://github.com/opendatalab/MinerU/raw/master/magic-pdf.template.json && \
#     cp magic-pdf.template.json /root/magic-pdf.json && \
#     source /opt/mineru_venv/bin/activate && \
#     pip3 install -U magic-pdf"

# # Download models and update the configuration file
# RUN /bin/bash -c "pip3 install huggingface_hub && \
#     wget https://github.com/opendatalab/MinerU/raw/master/scripts/download_models_hf.py -O download_models.py && \
#     python3 download_models.py && \
#     sed -i 's|cpu|cuda|g' /root/magic-pdf.json"

# # Append virtual environment activation to .bashrc
# RUN echo "source /opt/mineru_venv/bin/activate" >> ~/.bashrc

# # Set the working directory
# WORKDIR /workspace

# # Create directories for input and output images
# RUN mkdir -p /workspace/input_images /workspace/output_images && \
#     chmod -R 777 /workspace

# # Create and set up the front_ui folder
# RUN mkdir -p /workspace/front_ui && \
#     chmod -R 777 /workspace/front_ui



# # FROM HERE


# RUN apt-get update && apt-get install -y curl && \
#     rm -rf /var/lib/apt/lists/*

# RUN apt update && apt install -y systemd && apt clean

# RUN apt-get update && apt-get install -y \
#     pciutils \
#     lshw \
#     && apt-get clean

# RUN apt update && apt install -y ssh systemd

# RUN curl -fsSL https://ollama.com/install.sh | sh


# # UNTIL HERE

# # Set the entry point for persistent interactive shell
# ENTRYPOINT ["/bin/bash"]
