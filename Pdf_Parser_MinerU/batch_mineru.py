# Assume we have this running
#
# ```sh
#       docker run -it -d --name mineru \
#       --gpus=all \
#       -v /home/shared_space/Pdf_Parser_MinerU/mineru_xl/input:/workspace/input_images \
#       -v /home/shared_space/Pdf_Parser_MinerU/mineru_xl/output:/workspace/output_images \
#       ilabutk/mineru_ilab:0.2
# ```

import os
import subprocess
import shutil

# this has been mapped to docker `/workspace/input_images`
DOCKER_INPUT_FOLDER = "/home/shared_space/Pdf_Parser_MinerU/mineru_xl/input"  
DOCKER_OUTPUT_FOLDER = "/home/shared_space/Pdf_Parser_MinerU/mineru_xl/output"  

def copy_pdfs(input_folder, output_folder):
    """
    Copies all PDF files from the input folder to the output folder.
    
    Args:
        input_folder (str): Path to the directory containing PDF files.
        output_folder (str): Path to the destination directory.
    """
    os.makedirs(output_folder, exist_ok=True)
    
    for root, _, files in os.walk(input_folder):
        for file in files:
            if file.lower().endswith(".pdf"):  # Check if the file is a PDF
                src_path = os.path.join(root, file)
                dest_path = os.path.join(output_folder, file)
                try:
                    shutil.copy2(src_path, dest_path)
                    print(f"Copied: {src_path} -> {dest_path}")
                except Exception as e:
                    print(f"Error copying {src_path}: {e}")

def delete_files_in_folder(folder_path):
    """
    Deletes all files in the specified folder but leaves directories intact.

    Args:
        folder_path (str): Path to the folder where files will be deleted.
    """
    if not os.path.exists(folder_path):
        print(f"Folder '{folder_path}' does not exist.")
        return
    
    for file_name in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file_name)
        
        if os.path.isfile(file_path):  # Check if it's a file
            try:
                os.remove(file_path)  # Delete file
                print(f"Deleted: {file_path}")
            except Exception as e:
                print(f"Error deleting {file_path}: {e}")

def copy_contents(source_folder, destination_folder):
    """
    Copies all files and subfolders from source_folder to destination_folder.
    """
    if not os.path.exists(source_folder):
        print(f"Source folder '{source_folder}' does not exist.")
        return
    
    os.makedirs(destination_folder, exist_ok=True)

    for item in os.listdir(source_folder):
        source_path = os.path.join(source_folder, item)
        destination_path = os.path.join(destination_folder, item)

        try:
            if os.path.isdir(source_path):
                shutil.copytree(source_path, destination_path, dirs_exist_ok=True)
            else:
                shutil.copy2(source_path, destination_path)
            print(f"Copied: {source_path} -> {destination_path}")
        except PermissionError:
            print(f"Permission denied: {source_path}, trying with elevated permissions...")
            try:
                os.chmod(source_path, 0o777)  # Change permissions
                if os.path.isdir(source_path):
                    shutil.copytree(source_path, destination_path, dirs_exist_ok=True)
                else:
                    shutil.copy2(source_path, destination_path)
                print(f"Successfully copied after permission change: {source_path} -> {destination_path}")
            except Exception as e:
                print(f"Still unable to copy {source_path}: {e}")


            
def process_pdfs(input_folder, container_name="mineru"):
    """
    Walks through the input folder, finds all PDF files, and processes them using a Docker container.
    
    Args:
        input_folder (str): Path to the directory containing PDF files.
        container_name (str): Name of the running Docker container.
    """
    # Copy pdfs to DOCKER_INPUT_FOLDER to be processed
    copy_pdfs(input_folder, DOCKER_INPUT_FOLDER)
    
    # Ensure results folder exists: ./results by default under inputs
    output_folder = os.path.join(input_folder, 'results') 
    os.makedirs(output_folder, exist_ok=True)

    # Docker results path: Fixed
    docker_results_folder="/workspace/output_images/"
    
    # Walk through the input folder
    for root, _, files in os.walk(DOCKER_INPUT_FOLDER):
        for file in files:
            if file.lower().endswith(".pdf"):  # Check if the file is a PDF
                docker_pdf_path = f"/workspace/input_images/{file}" # inside docker - it has been mapped
                command = [
                    "docker", "exec", "-it", container_name, "bash", "-c",
                    f"'/opt/mineru_venv/bin/magic-pdf -p \"{docker_pdf_path}\" -o \"{docker_results_folder}\" -m auto'"
                ]
                
                try:
                    print(f"Processing: {file}")
                    subprocess.run(" ".join(command), shell=True, check=True)
                except subprocess.CalledProcessError as e:
                    print(f"Error processing {docker_pdf_path}: {e}")
    
    # clear DOCKER_INPUT_FOLDER 
    delete_files_in_folder(DOCKER_INPUT_FOLDER)
    # copy DOCKER_OUTPUT_FOLDER
    copy_contents(DOCKER_OUTPUT_FOLDER, output_folder)
    # remove from inside
    command = [
        "docker", "exec", "mineru", "bash", "-c",
        f"cd {docker_results_folder} && rm -rf *"
    ]
    
    try:
        print(f"Cleaning output folder: {docker_results_folder}")
        subprocess.run(command, shell=False, check=True)  # Use shell=False for security
    except subprocess.CalledProcessError as e:
        print(f"Error cleaning folder {docker_results_folder}: {e}")


if __name__ == "__main__":    
    """
        Provide a source folder. Processed files will be under the ./results subfolder.
    """
    # input_folder = "/home/shared_space/Pdf_Parser_MinerU/use_cases/tmp/"    
    # input_folder = "/home/shared_space/Pdf_Parser_MinerU/use_cases/nccn_bible/"
    # input_folder = "/home/shared_space/Pdf_Parser_MinerU/use_cases/crstar_abstract_2023/" 
    input_folder = "/home/shared_space/Pdf_Parser_MinerU/use_cases/my_pubs/" 
    process_pdfs(input_folder)
