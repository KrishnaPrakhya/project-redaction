from posixpath import dirname
from flask import Flask,jsonify,request,json,send_from_directory,url_for
from flask_cors import CORS
import fitz  
import re
import sys
import torch
import uuid
from gliner import GLiNERConfig,GLiNER
from gliner.training import Trainer,TrainingArguments
from gliner.data_processing.collator import DataCollatorWithPadding,DataCollator
from gliner.utils import load_config_as_namespace
from gliner.data_processing import WordsSplitter,GLiNERDataset
import os
import requests
import torch.nn as nn
import torchvision.transforms.functional as TF
import torchvision
from PIL import Image
import numpy as np
import cv2
from UNET import UNET

app=Flask(__name__)
CORS(app)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
IMAGE_DIRECTORY = os.path.join(os.getcwd(), "redacted_images")
print(IMAGE_DIRECTORY)
model = GLiNER.from_pretrained("urchade/gliner_small-v2.1")
labels = [
    "Person",
    "name",
    "DATE",
    "age",
    "ACCOUNT INFORMATION",
    "TRANSACTION DETAILS",
    "INVESTMENT DETAILS",
    "LOAN DETAILS",
    "INSURANCE POLICIES",
    "INCOME AND EARNINGS",
    "EXPENDITURE AND BUDGET",
    "TAX DETAILS",
    "ACADEMIC RECORDS",
    "ENROLLMENT DETAILS",
    "COURSES AND PROGRAMS",
    "ASSESSMENTS AND EXAMS",
    "EXTRACURRICULAR ACTIVITIES",
    "SCHOLARSHIPS",
    "ATTENDANCE AND DISCIPLINE",
    "PROJECTS AND ASSIGNMENTS"
]

segment_model = UNET(in_channels=3, out_channels=1).to(DEVICE)
checkpoint = torch.load("./chrs_ep28.pth.tar", map_location=DEVICE)
segment_model.load_state_dict(checkpoint["state_dict"])
segment_model.eval()


@app.route('/api/data',methods=['GET'])
def get_data():
  return jsonify({"message":"THis is a message"})

@app.route('/api/upload', methods=['POST'])
def upload_data():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    if file:
        print(f"File received: {file.filename}")
        return jsonify({"file": "Uploaded successfully"}), 200
    else:
        return jsonify({"error": "No file uploaded"}), 400



@app.route('/api/redactEntity',methods=['POST'])
def redactEntity():
    pdf_file = request.files.get('file')
    print(pdf_file)
    if not pdf_file:
        return jsonify({"error": "File not provided"}), 400

    entities = request.form.get('entities')
    if not entities:
        return jsonify({"error": "Entities not provided"}), 400
    try:
        entities = json.loads(entities)
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON for entities"}), 400
    
    redact_type=request.args.get('type')
    print(redact_type)
    entities_categories_list=[]
    entities_list=[]
    print(entities)
    for i in entities:
        entities_list.append(i['text'])
        entities_categories_list.append(i['label'])
    print(entities_list)
    print(entities_categories_list)
    pdf_content = pdf_file.read()
    with fitz.open(stream=pdf_content, filetype="pdf") as doc:
        for page in doc:
            for word, entity in zip(entities_list, entities_categories_list):
                # print(word)
                # print(entity)
                areas = page.search_for(word)
                for area in areas:
                    if redact_type == "BlackOut":
                        page.add_redact_annot(area, fill=(0, 0, 0))
                    elif redact_type == "Vanishing":
                        page.add_redact_annot(area, fill=(1, 1, 1))
                    elif redact_type == "Blurring":
                        page.add_redact_annot(area, fill=(1, 1, 0))
                    elif redact_type=="CategoryReplacement":
                        font_size = (area[3]-area[1])*0.6
                        print(font_size)
                        annot = page.add_redact_annot(area, text = entity, text_color = fitz.utils.getColor("black"), fontsize = font_size)
                        annot.update()
                        print("Level2")
                        print("hnfdn")
                    elif redact_type=="SyntheticReplacement":
                        print("Level3")
                        print("fdj")
            page.apply_redactions()
        redacted_file = f"new2.pdf"
        doc.save(redacted_file) 

    return jsonify({
        "message": "File redacted successfully",
        "output_file": redacted_file
    }), 200



@app.route('/api/get-redacted-image', methods=['GET'])
def get_redacted_image():
    filename = "resme.jpeg"
    return send_from_directory(IMAGE_DIRECTORY, filename, as_attachment=False)
@app.route('/api/redactImage', methods=['POST'])
def redact_image_api():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({"error": "No file uploaded"}), 400

    output_dir = './redacted_images'
    os.makedirs(output_dir, exist_ok=True)

    input_path = os.path.join(output_dir, file.filename)
    file.save(input_path)

    try:
        masking(segment_model, input_path, output_dir)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    redacted_path = os.path.join(output_dir, file.filename)
    file_url = url_for('get_redacted_image', _external=True)
    return jsonify({
        "message": "Image redacted successfully",
        "output_file": redacted_path,
        "file_url": file_url
    }), 200


def masking(model, image_path, output_dir):

    def preprocess_image(image):
        transform = torchvision.transforms.Compose([
            torchvision.transforms.Resize((1056, 816)),
            torchvision.transforms.ToTensor(),
            torchvision.transforms.Normalize(mean=[0.0, 0.0, 0.0], std=[1.0, 1.0, 1.0]),
        ])
        image = transform(image)
        image = image.unsqueeze(0)
        return image.to(DEVICE)

    def predict_mask(image):
        input_image = preprocess_image(image)
        with torch.no_grad():
            prediction = model(input_image)
            prediction = torch.sigmoid(prediction)
            mask = (prediction > 0.5).float()
            mask = mask.squeeze(0).cpu()
        return mask

    def redact_image(image, mask):
        mask = mask.resize(image.size)
        kernel = np.ones((3, 3), np.uint8)
        mask_np = np.array(mask)

        mask = Image.fromarray(mask_np)
        image_np = np.array(image)
        mask_np = np.array(mask)
        mask_np = cv2.erode(mask_np, kernel, iterations=1)
        image_np[mask_np > 0] = 0
        redacted_image = Image.fromarray(image_np)
        return redacted_image


    try:
        img = Image.open(image_path).convert("RGB")
    except FileNotFoundError:
        print(f"Error: Image file not found at {image_path}")
        return

    original_width, original_height = img.size
    image_name = os.path.basename(image_path)

    mask = predict_mask(img)
    mask_image = TF.to_pil_image(mask)
    mask_image = mask_image.resize((original_width, original_height), Image.Resampling.BICUBIC)

    redacted_img = redact_image(img, mask_image)

    output_path = os.path.join(output_dir, image_name)
    redacted_img.save(output_path)
    print(f"Redacted image saved to: {output_path}")

  


@app.route('/api/entities', methods=['POST'])
def entities():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({"error": "No file uploaded"}), 400

    pdf_content = file.read()
    
    full_texts = ""
    with fitz.open(stream=pdf_content, filetype="pdf") as doc:
        for page in doc:
            full_texts += page.get_text()

    def preprocess_whitespace(text):
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    cleaned_text = preprocess_whitespace(full_texts)

    entities = model.predict_entities(cleaned_text, labels, threshold=0.5)
    redact_words = []
    entity_list = []

    for entity in entities:
        entity_list.append({"text":entity["text"],"label":entity["label"]})
        redact_words.append(entity["text"])

    

    return jsonify({
        "message": "File redacted successfully",
        # "output": redacted_file,
        "entities": entity_list
    }), 200
if __name__ == "__main__":
    app.run( port=5000, debug=True)