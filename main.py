import os
import json
import traceback
from flask import Flask, request, redirect, send_file, jsonify
from google.cloud import storage
import google.generativeai as genai

# Initialize Flask app
app = Flask(__name__)

# Google Cloud Storage Configuration
storage_client = storage.Client()
BUCKET_NAME = "sutcliff-fau-cloud-native"
LOCAL_DIR = "files"

# Ensure local directory exists
os.makedirs(LOCAL_DIR, exist_ok=True)

# Initialize Gemini AI API Key
genai.configure(api_key=os.environ['GEMINI_API_KEY'])

# Define the generation config
generation_config = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 64,
    "max_output_tokens": 8192,
    "response_mime_type": "application/json",
}

# Initialize Gemini AI Model (Updated to Gemini 2.0)
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    generation_config=generation_config,
)

# Prompt for AI model
PROMPT = "Please generate a title and 1 paragraph description for the image. Your response should be in JSON format with only 2 attributes: title and description."

def upload_to_gcs(bucket_name, file_path, blob_name):
    """Uploads a file to Google Cloud Storage."""
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(file_path)

def download_from_gcs(bucket_name, file_name):
    """Downloads a file from Google Cloud Storage."""
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(file_name)
    local_path = os.path.join(LOCAL_DIR, file_name)
    blob.download_to_filename(local_path)
    return local_path

def get_gcs_files(bucket_name):
    """Lists all files in the GCS bucket."""
    bucket = storage_client.bucket(bucket_name)
    return [blob.name for blob in bucket.list_blobs()]

def upload_to_gemini(path, mime_type="image/jpeg"):
    """Uploads the given file to Gemini."""
    file = genai.upload_file(path, mime_type=mime_type)
    print(f"Uploaded file '{file.display_name}' as: {file.uri}")
    return file

def generate_image_caption(image_path):
    """Uses Gemini 2.0 AI to generate a title and description for an image."""
    # try:
    # Upload file to Gemini
    gemini_file = upload_to_gemini(image_path, mime_type="image/jpeg")

    # Send request to Gemini AI
    response = model.generate_content(
        [gemini_file, "\n\n", PROMPT]
    )

    print("🔹 Raw Gemini AI Response:", response.text)

    # Convert response to JSON format
    response_text = response.text.strip()

    # Ensure correct JSON parsing
    metadata = json.loads(response_text) if response_text else {"title": "Untitled", "description": "No description available."}

    # except (json.JSONDecodeError, AttributeError):
    #     print("Error: Failed to parse JSON response from Gemini AI")
    #     metadata = {"title": "Untitled", "description": "No description available."}

    return metadata

@app.route('/')
def index():
    """Displays the file upload form and list of files."""
    index_html = """
    <form method="post" enctype="multipart/form-data" action="/upload">
        <label for="file">Choose file to upload</label>
        <input type="file" id="file" name="form_file" accept="image/jpeg"/>
        <button>Submit</button>
    </form>
    <hr><table width="80%" align="center">
    """

    idx = 0
    for file in get_gcs_files(BUCKET_NAME):
        if file.endswith(".jpeg") or file.endswith(".jpg"):
            idx += 1
            if idx % 2 == 1:
                index_html += "<tr>"
            index_html += f"""
                <td width="50%">
                    <a href="/files/{file}">
                        <img width="100%" src="/image/{file}">
                    </a>
                </td>
            """
            if idx % 2 == 0:
                index_html += "</tr>"

    index_html += "</table>"
    return index_html

@app.route('/upload', methods=["POST"])
def upload():
    """Handles file upload and metadata generation."""
    try:
        file = request.files['form_file']
        local_path = os.path.join(LOCAL_DIR, file.filename)
        file.save(local_path)

        # Upload image to GCS
        upload_to_gcs(BUCKET_NAME, local_path, file.filename)

        # Generate caption using Gemini AI
        metadata = generate_image_caption(local_path)

        # Save metadata to a JSON file
        json_path = local_path.replace(".jpeg", ".json").replace(".jpg", ".json")
        with open(json_path, "w") as json_file:
            json.dump(metadata, json_file)

        # Upload JSON to GCS
        json_filename = file.filename.replace(".jpeg", ".json").replace(".jpg", ".json")
        upload_to_gcs(BUCKET_NAME, json_path, json_filename)

        # Clean up local files
        os.remove(local_path)
        os.remove(json_path)

        return redirect(f"/files/{file.filename}")

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/files/<filename>')
def get_file(filename):
    """Fetches the image and its corresponding JSON metadata."""
    try:
        image_path = download_from_gcs(BUCKET_NAME, filename)
        json_path = download_from_gcs(BUCKET_NAME, filename.replace(".jpeg", ".json").replace(".jpg", ".json"))

        with open(json_path, "r") as json_file:
            metadata = json.load(json_file)

        image_html = f"""
        <h2>{metadata['title']}</h2>
        <img src="/image/{filename}" width="500">
        <p>{metadata['description']}</p>
        <p><a href="/">Back</a></p>
        """
        return image_html
    except Exception as e:
        traceback.print_exc()
        return f"<p>Error fetching file: {str(e)}</p>"

@app.route('/image/<filename>')
def get_image(filename):
    """Serves an image from the local directory."""
    return send_file(os.path.join(LOCAL_DIR, filename))

if __name__ == '__main__':
    app.run(debug=True)
