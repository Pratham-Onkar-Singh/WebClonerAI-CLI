import requests
import subprocess
import os

from bs4 import BeautifulSoup
import json
from urllib.parse import urljoin

# Get the current working directory where the script runs
BASE_DIR = os.getcwd()
CLONED_DIR = os.path.join(BASE_DIR, "cloned_website")
ASSETS_DIR = os.path.join(CLONED_DIR, "assets")

def fetch_url(url: str) -> str:
    """Fetches and summarizes the HTML content to save tokens."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Use Python to do the hard work instead of the LLM
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Extract only what the LLM needs to know
        image_urls = []
        for img in soup.find_all("img", src=True):
            full_url = urljoin(url, img["src"])
            if full_url not in image_urls:
                image_urls.append(full_url)
                
        # Return a tiny JSON summary instead of massive HTML code
        summary = {
            "title": soup.title.get_text(strip=True) if soup.title else "No Title",
            "images_to_download": image_urls[:15], # Limit to 15 images
            "text_content_preview": soup.get_text(separator=" ", strip=True)[:1000]
        }
        
        return json.dumps(summary, indent=2)
        
    except Exception as e:
        return f"Error fetching URL: {str(e)}"

def write_file(filename: str, content: str) -> str:
    """Writes content to a file in the cloned_website directory."""
    try:
        # Create cloned_website directory if it doesn't exist
        os.makedirs(CLONED_DIR, exist_ok=True)
        
        # Sanitize filename - remove any leading cloned_website/ paths
        filename = filename.lstrip("./\\")
        if filename.startswith("cloned_website"):
            filename = filename.replace("cloned_website/", "", 1).replace("cloned_website\\", "", 1)
        
        # Use absolute path in cloned_website directory
        filepath = os.path.join(CLONED_DIR, filename)
        
        # Ensure subdirectories exist
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to cloned_website/{filename}"
    except Exception as e:
        return f"Error writing file: {str(e)}"

def execute_command(command: str) -> str:
    """Executes a shell command in the cloned_website directory."""
    try:
        # Ensure assets directory structure exists BEFORE any command
        os.makedirs(os.path.join(CLONED_DIR, "assets", "images"), exist_ok=True)
        os.makedirs(os.path.join(CLONED_DIR, "assets", "icons"), exist_ok=True)
        
        # Reject any mkdir or directory creation commands - they're not needed
        if "mkdir" in command.lower() or "-p" in command:
            return "Directory structure already created. Skip mkdir and proceed with downloads."
        
        # Run command in cloned_website directory
        result = subprocess.run(
            command, 
            shell=True, 
            capture_output=True, 
            text=True, 
            timeout=30,
            cwd=CLONED_DIR
        )
        if result.returncode == 0:
            output = result.stdout if result.stdout else "Success."
            return output[:500] + "... (truncated)" if len(output) > 500 else output
        else:
            return f"Error executing command: {result.stderr}"
    except Exception as e:
        return f"Exception during execution: {str(e)}"

def read_file(filename: str) -> str:
    """Reads the content of a file from the cloned_website directory."""
    try:
        # Sanitize filename - remove any leading cloned_website/ paths
        filename = filename.lstrip("./\\")
        if filename.startswith("cloned_website"):
            filename = filename.replace("cloned_website/", "", 1).replace("cloned_website\\", "", 1)
        
        filepath = os.path.join(CLONED_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

def list_files(directory: str = ".") -> str:
    """Lists files in the cloned_website directory."""
    try:
        os.makedirs(CLONED_DIR, exist_ok=True)
        if directory == "." or directory == "cloned_website":
            dirpath = CLONED_DIR
        elif directory == "assets" or directory.startswith("assets"):
            dirpath = os.path.join(CLONED_DIR, directory)
        else:
            dirpath = os.path.join(CLONED_DIR, directory)
        
        os.makedirs(dirpath, exist_ok=True)
        files = os.listdir(dirpath)
        return "\n".join(files) if files else "Directory is empty"
    except Exception as e:
        return f"Error listing files: {str(e)}"

# Map of available tools for the agent to use
TOOL_MAP = {
    "fetch_url": fetch_url,
    "write_file": write_file,
    "read_file": read_file,
    "list_files": list_files,
    "execute_command": execute_command
}
