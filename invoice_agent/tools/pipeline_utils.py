# invoice_agent/tools/pipeline_utils.py
import os
import json
import mimetypes
import re
import pandas as pd
from io import BytesIO, StringIO
from datetime import datetime

# Google Cloud and Gemini Imports
import google.generativeai as genai
from google.cloud import storage

# Local package imports
from .. import prompts

# --- HELPER FUNCTIONS ---

def _get_blob(storage_client, bucket_name, blob_name):
    bucket = storage_client.bucket(bucket_name)
    return bucket.blob(blob_name)

def _move_blob(storage_client, bucket_name, blob, new_prefix):
    if not blob.exists():
        print(f"⚠️ Blob {blob.name} does not exist. Cannot move.")
        return None
    
    original_filename = os.path.basename(blob.name)
    new_blob_name = f"{new_prefix}/{original_filename}"
    
    bucket = storage_client.bucket(bucket_name)
    new_blob = bucket.copy_blob(blob, bucket, new_blob_name)
    blob.delete()
    print(f"✅ Moved gs://{bucket_name}/{blob.name} to gs://{bucket_name}/{new_blob_name}")
    return new_blob

def _convert_xlsx_to_csv_bytes(xlsx_bytes):
    try:
        df = pd.read_excel(BytesIO(xlsx_bytes), engine='openpyxl')
        return df.to_csv(index=False).encode('utf-8')
    except Exception as e:
        print(f"❌ Error converting XLSX bytes to CSV: {e}")
        return None

# --- AGENT TOOLS ---

def setup_gcs_folders(gcs_location: str):
    """
    Sets up the necessary folder structure in GCS if the provided location is empty.
    """
    match = re.match(r"gs://([^/]+)/?(.*)", gcs_location)
    if not match:
        return "Invalid GCS location format. Please use gs://<bucket_name>/<prefix>."
    
    bucket_name, prefix = match.groups()
    prefix = prefix.rstrip('/') + '/' if prefix else ''

    storage_client = storage.Client(project=os.getenv("GCP_PROJECT_ID"))
    bucket = storage_client.bucket(bucket_name)

    # Check if the prefix is empty and create folders if needed
    blobs = list(bucket.list_blobs(prefix=prefix, max_results=1))
    if not blobs:
        print(f"Provided GCS location gs://{bucket_name}/{prefix} is empty. Creating necessary folders...")
        for folder in ["input_invoices/", "sorted_invoices/", "error_invoices/", "gemini_output/", "ground_truth/", "reports/"]:
            blob = bucket.blob(f"{prefix}{folder}")
            blob.upload_from_string('')
            print(f"  - Created gs://{bucket_name}/{prefix}{folder}")
        return f"Successfully created folders in gs://{bucket_name}/{prefix}. Please upload your input invoices to the '{prefix}input_invoices/' folder and your ground truth JSON files to the '{prefix}ground_truth/' folder."
    else:
        return f"GCS location gs://{bucket_name}/{prefix} is not empty. Skipping folder creation."

def route_invoices(gcs_location: str):
    """
    Routes invoices from the 'input_invoices' folder to vendor-specific folders.
    """
    match = re.match(r"gs://([^/]+)/?(.*)", gcs_location)
    if not match:
        return "Invalid GCS location format. Please use gs://<bucket_name>/<prefix>."
    
    bucket_name, prefix = match.groups()
    prefix = prefix.rstrip('/') + '/' if prefix else ''

    storage_client = storage.Client(project=os.getenv("GCP_PROJECT_ID"))
    model = genai.GenerativeModel("gemini-1.5-pro-latest")
    bucket = storage_client.bucket(bucket_name)
    
    input_blobs = [b for b in bucket.list_blobs(prefix=f"{prefix}input_invoices/") if not b.name.endswith('/')]
    if not input_blobs: return "No new invoices found."
    
    processed_count = 0
    error_count = 0
    error_invoices = []
    
    for blob in input_blobs:
        try:
            file_bytes = blob.download_as_bytes()
            
            if blob.name.endswith('.xlsx'):
                content = _convert_xlsx_to_csv_bytes(file_bytes)
                if not content: raise ValueError("File conversion failed.")
                mime = "text/csv"
            else:
                content = file_bytes
                mime, _ = mimetypes.guess_type(blob.name)

            response = model.generate_content([prompts.get_routing_prompt(), {"mime_type": mime, "data": content}])
            seller = response.text.strip().replace(" ", "_").replace("/", "_") or "Unknown_Vendor"
            
            new_blob = _move_blob(storage_client, bucket_name, blob, f"{prefix}sorted_invoices/{seller}")
            if new_blob:
                processed_count += 1
        except Exception as e:
            print(f"❌ Routing Error for {blob.name}: {e}")
            error_count += 1
            error_invoices.append(blob.name)
            _move_blob(storage_client, bucket_name, blob, f"{prefix}error_invoices")
    
    report = f"Routing process completed.\n"
    report += f"Successfully processed: {processed_count}\n"
    report += f"Errors: {error_count}\n"
    if error_invoices:
        report += f"Error invoices moved to error folder: {', '.join(error_invoices)}"
        
    return report

def extract_data(gcs_location: str):
    """
    Extracts data from invoices in the 'sorted_invoices' folder and saves it as JSON.
    """
    match = re.match(r"gs://([^/]+)/?(.*)", gcs_location)
    if not match:
        return "Invalid GCS location format. Please use gs://<bucket_name>/<prefix>."
    
    bucket_name, prefix = match.groups()
    prefix = prefix.rstrip('/') + '/' if prefix else ''

    storage_client = storage.Client(project=os.getenv("GCP_PROJECT_ID"))
    model = genai.GenerativeModel("gemini-1.5-pro-latest")
    bucket = storage_client.bucket(bucket_name)

    sorted_blobs = [b for b in bucket.list_blobs(prefix=f"{prefix}sorted_invoices/") if not b.name.endswith('/')]
    if not sorted_blobs: return "No sorted invoices found."

    processed_count = 0
    error_count = 0
    error_invoices = []

    for blob in sorted_blobs:
        base_filename = os.path.splitext(os.path.basename(blob.name))[0]
        try:
            file_bytes = blob.download_as_bytes()
            
            if blob.name.endswith('.xlsx'):
                content = _convert_xlsx_to_csv_bytes(file_bytes)
                if not content: raise ValueError("File conversion failed.")
                mime = "text/csv"
            else:
                content = file_bytes
                mime, _ = mimetypes.guess_type(blob.name)

            response = model.generate_content([prompts.get_extraction_prompt(), {"mime_type": mime, "data": content}])
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if not match: raise ValueError("No JSON found in extraction response.")
            
            output_blob = _get_blob(storage_client, bucket_name, f"{prefix}gemini_output/{base_filename}.json")
            output_blob.upload_from_string(match.group(), content_type='application/json')
            processed_count += 1
            print(f"✅ Extracted JSON for: {base_filename}")
        except Exception as e:
            print(f"❌ Extraction Error for {blob.name}: {e}")
            error_count += 1
            error_invoices.append(blob.name)
            _move_blob(storage_client, bucket_name, blob, f"{prefix}error_invoices")
            
    report = f"Extraction process completed.\n"
    report += f"Successfully processed: {processed_count}\n"
    report += f"Errors: {error_count}\n"
    if error_invoices:
        report += f"Error invoices moved to error folder: {', '.join(error_invoices)}"
        
    return report

def evaluate_extractions(gcs_location: str):
    """
    Evaluates the extracted invoice data against the ground truth and generates a report.
    """
    match = re.match(r"gs://([^/]+)/?(.*)", gcs_location)
    if not match:
        return "Invalid GCS location format. Please use gs://<bucket_name>/<prefix>."
    
    bucket_name, prefix = match.groups()
    prefix = prefix.rstrip('/') + '/' if prefix else ''

    storage_client = storage.Client(project=os.getenv("GCP_PROJECT_ID"))
    model = genai.GenerativeModel("gemini-1.5-pro-latest")
    bucket = storage_client.bucket(bucket_name)

    DEAL_BREAKERS = {
        "invoice.client_name",
        "invoice.seller_name",
        "invoice.invoice_number",
        "invoice.invoice_date",
        "subtotal.total",
    }

    extracted_blobs = [b for b in bucket.list_blobs(prefix=f"{prefix}gemini_output/") if not b.name.endswith('/')]
    if not extracted_blobs: return "No extracted data found."

    extracted_files_map = {os.path.splitext(os.path.basename(b.name))[0]: b.name for b in extracted_blobs}

    all_results = []
    for gt_blob in bucket.list_blobs(prefix=f"{prefix}ground_truth/"):
        if gt_blob.name.endswith('/'): continue
        base_filename = os.path.splitext(os.path.basename(gt_blob.name))[0]
        
        if base_filename not in extracted_files_map:
            all_results.append({"invoice": base_filename, "status": "Error", "details": "Gemini Output Not Found"})
            continue
        try:
            gt_data = json.loads(gt_blob.download_as_string())
            out_blob = _get_blob(storage_client, bucket_name, extracted_files_map[base_filename])
            out_data = json.loads(out_blob.download_as_string())
            
            eval_prompt = prompts.get_evaluation_prompt(gt_data, out_data, DEAL_BREAKERS, base_filename)
            response = model.generate_content(eval_prompt)
            cleaned_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
            verdict = json.loads(cleaned_text)
            
            result = {"invoice": base_filename, "status": verdict.get("overall_status", "Parse Error")}
            result["details"] = verdict.get("mismatches", []) if result["status"] == "Mismatch" else []
            all_results.append(result)
            print(f"✅ Evaluation complete for {base_filename}: {result['status']}")
        except Exception as e:
            all_results.append({"invoice": base_filename, "status": "Error", "details": str(e)})

    report_data = []
    for res in all_results:
        if res['status'] == "Mismatch" and res['details']:
            for mismatch in res['details']: report_data.append([res['invoice'], res['status'], mismatch.get('field', 'N/A'), mismatch.get('expected', 'N/A'), mismatch.get('actual', 'N/A')])
        else:
            report_data.append([res['invoice'], res['status'], "-", "-", res.get('details', '-') if res['status'] == "Error" else "-"])
    
    df = pd.DataFrame(report_data, columns=["Invoice", "Overall Status", "Field", "Expected", "Actual"])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_blob_name = f"{prefix}reports/evaluation_report_{timestamp}.csv"
    _get_blob(storage_client, bucket_name, report_blob_name).upload_from_string(df.to_csv(index=False), content_type='text/csv')
    
    final_message = f"Pipeline finished. Report is available at: gs://{bucket_name}/{report_blob_name}"
    print(f"\n✅ {final_message}")
    return final_message
