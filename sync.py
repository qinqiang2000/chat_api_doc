import re
import streamlit as st
import requests
import os
import tempfile
import random
import string
from openai import OpenAI
from typing import Dict, Any, List
from datetime import datetime
from openai_assistant import Assistant

def extract_markdown_links(content):    
    # Pattern to match markdown links: [text](url)
    pattern = r'\[([^\]]+)\]\(([^)]+)\)'
    matches = re.findall(pattern, content)
    
    # Filter only .md links
    md_links = [(text, url) for text, url in matches if url.endswith('.md')]
    return md_links

def setup_ui_containers():
    """Create and return UI containers for status and logging."""
    status = st.empty()
    with st.expander("Detailed Progress Log", expanded=True):
        log_container = st.container()
    return status, log_container

def create_temp_directory(assistant_id: str) -> str:
    """Create a temporary directory for file downloads.
    
    Args:
        assistant_id: The ID of the assistant
    Returns:
        str: Path to the created temporary directory
    """
    random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    temp_dir = os.path.join("tmp", f"sync_{assistant_id}_{random_suffix}")
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir

def download_markdown_files(llm_txt_url: str, temp_dir: str, status, log_container) -> None:
    """Download markdown files from llm.txt URL.
    
    Args:
        llm_txt_url: URL to the llm.txt file
        temp_dir: Directory to save downloaded files
        status: Streamlit status container
        log_container: Streamlit log container
    """
    status.write(f"Downloading llm.txt from {llm_txt_url}")
    response = requests.get(llm_txt_url)
    response.raise_for_status()
    md_links = extract_markdown_links(response.text.strip())
    log_container.info(f"Found {len(md_links)} markdown files to download")

    for i, (text, url) in enumerate(md_links, 1):
        if not url.strip():
            continue
        status.write(f"Downloading file {i}/{len(md_links)}: {url}")
        
        clean_text = clean_filename(text)
        filename = os.path.join(temp_dir, f"{clean_text}.md")
        
        response = requests.get(url)
        response.raise_for_status()
        with open(filename, 'wb') as f:
            f.write(response.content)
        log_container.info(f"Successfully downloaded {filename}")

def clean_filename(text: str) -> str:
    """Clean filename to remove invalid characters and limit length.
    
    Args:
        text: Original filename
    Returns:
        str: Cleaned filename
    """
    # Remove invalid filename characters
    clean_text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', text)
    # Remove leading/trailing spaces and dots
    clean_text = clean_text.strip('. ')
    # Limit filename length
    if len(clean_text) > 100:
        clean_text = clean_text[:97] + "..."
    return clean_text

def update_assistant_files(client: OpenAI, assistant_id: str, temp_dir: str, status, log_container) -> None:
    """Update assistant's files by removing old ones and uploading new ones.
    
    Args:
        client: OpenAI client instance
        assistant_id: The ID of the assistant
        temp_dir: Directory containing new files
        status: Streamlit status container
        log_container: Streamlit log container
    """
    try:
        # 创建 Assistant 实例
        assistant = Assistant(assistant_id=assistant_id, client=client)
        
        # 清空现有文件
        status.write("Deleting existing files from assistant...")
        if not assistant.empty_files():
            log_container.error("Failed to empty existing files")
            return
            
        # 准备文件路径和URL列表
        files_to_upload = [f for f in os.listdir(temp_dir) if f.endswith('.md')]
        file_paths_and_urls = []
        for filename in files_to_upload:
            file_path = os.path.join(temp_dir, filename)
            # 由于是本地文件，URL可以设为空字符串
            file_paths_and_urls.append(("", file_path))
            
        # 创建新的向量库并上传文件
        status.write("Uploading new files to assistant...")
        if not assistant.create_vs(file_paths_and_urls):
            log_container.error("Failed to create vector store and upload files")
            return
            
        log_container.info("Successfully updated assistant files")
        status.success("All files updated successfully!")
        
    except Exception as e:
        log_container.error(f"Error updating files: {str(e)}")
        status.error(f"Error updating files: {str(e)}")
        raise

def delete_storage_files(client: OpenAI, file_ids: List[str], status, log_container) -> None:
    """Delete files from OpenAI storage.
    
    Args:
        client: OpenAI client instance
        file_ids: List of file IDs to delete
        status: Streamlit status container
        log_container: Streamlit log container
    """
    for i, file_id in enumerate(file_ids, 1):
        status.write(f"Deleting file {i}/{len(file_ids)}: {file_id}")
        try:
            client.files.delete(file_id=file_id)
            log_container.info(f"Successfully deleted file {file_id}")
        except Exception as e:
            log_container.warning(f"Failed to delete file {file_id}: {str(e)}")

def upload_new_files(client: OpenAI, temp_dir: str, status, log_container) -> List[str]:
    """Upload new files to OpenAI storage.
    
    Args:
        client: OpenAI client instance
        temp_dir: Directory containing files to upload
        status: Streamlit status container
        log_container: Streamlit log container
    Returns:
        List[str]: List of new file IDs
    """
    status.write("Uploading new files to assistant...")
    files_to_upload = [f for f in os.listdir(temp_dir) if f.endswith('.md')]
    log_container.info(f"Found {len(files_to_upload)} files to upload")
    
    new_file_ids = []
    for i, filename in enumerate(files_to_upload, 1):
        status.write(f"Uploading file {i}/{len(files_to_upload)}: {filename}")
        with open(os.path.join(temp_dir, filename), 'rb') as f:
            file = client.files.create(file=f, purpose='assistants')
            new_file_ids.append(file.id)
        log_container.info(f"Successfully uploaded {filename}")
    
    return new_file_ids

def sync_assistant_files(client: OpenAI, assistant: Dict[str, Any]) -> None:
    """
    Sync files for an assistant by downloading from llm.txt and updating the assistant's files.
    
    Args:
        client: OpenAI client instance
        assistant: Assistant configuration dictionary
    """
    st.write("Starting file sync process...")
    
    try:
        # Setup UI
        back = st.empty()
        status, log_container = setup_ui_containers()
        
        # Create temporary directory
        temp_dir = create_temp_directory(assistant.get("id", "unknown"))
        log_container.info(f"Created temporary directory: {temp_dir}")
        
        # Check llm.txt URL
        llm_txt_url = assistant.get("llm_txt_url")
        if not llm_txt_url:
            status.error("No llm.txt URL configured for this assistant")
            return

        # Download markdown files
        download_markdown_files(llm_txt_url, temp_dir, status, log_container)
        
        # Update assistant files
        update_assistant_files(client, assistant["id"], temp_dir, status, log_container)
        
        status.success("All files updated successfully!")
        
        # Add hyperlink to return to the chat page with only type parameter
        current_type = st.query_params.get("type")
        if current_type:
            chat_url = f"/?type={current_type}"
            back.markdown(f"[返回聊天页面]({chat_url})")

    except Exception as e:
        status.error(f"Error updating files: {str(e)}")
        log_container.exception(e)  # This will show the full traceback 