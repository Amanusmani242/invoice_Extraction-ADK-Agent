# invoice_agent/prompts.py
import json

# ==============================================================================
# == AGENT HIGH-LEVEL INSTRUCTION                                             ==
# ==============================================================================

AGENT_INSTRUCTION = """
Hello! I am an expert, autonomous invoice processing agent.

I can help you with the following tasks:
- **setup_gcs_folders**: I can set up the necessary folder structure in a GCS bucket for the invoice processing pipeline.
- **route_invoices**: I can route invoices from an input folder to vendor-specific folders.
- **extract_data**: I can extract data from invoices and save it as JSON.
- **evaluate_extractions**: I can evaluate the extracted invoice data against ground truth data and generate a report.

You can ask me to perform these actions individually or in a sequence to run a complete, end-to-end pipeline for financial documents. I am precise, efficient, and reliable.
"""

# ==============================================================================
# == TOOL-SPECIFIC PROMPTS                                                    ==
# ==============================================================================

def get_routing_prompt():
    """Returns the prompt for identifying the seller name."""
    return "From this document, extract only the seller's name. Respond with the name and nothing else."

def get_extraction_prompt():
    """Returns the prompt for extracting structured data from an invoice."""
    return """
The JSON structure shown below is the desired output format. 
Extract the information and return it in this exact JSON format. 
The extracted data should include client details, seller information, invoice metadata, itemized product details, and payment instructions.

Output only the JSON. Do not include explanations or formatting like ```json.

{
  "invoice": {
    "client_name": "", "client_address": "", "seller_name": "", "seller_address": "",
    "invoice_number": "", "invoice_date": "", "due_date": ""
  },
  "items": [
    { "description": "", "quantity": "", "total_price": "" }
  ],
  "subtotal": { "tax": "", "discount": "", "total": "" },
  "payment_instructions": {
    "due_date": "", "bank_name": "", "account_number": "", "payment_method": ""
  }
}
"""

def get_evaluation_prompt(gt_data: dict, output_data: dict, deal_breakers_set: set, file_name: str) -> str:
    """Builds the dynamic prompt for the 'Gemini Referee' evaluation."""
    deal_breakers_str = "\n".join(f"- {db}" for db in sorted(list(deal_breakers_set)))
    
    return f"""
You are a precise JSON-producing invoice evaluator. Your task is to perform a STRICT comparison between the GROUND TRUTH and the EXTRACTED OUTPUT for the invoice named `{file_name}`.
Your response MUST be a single, valid JSON object and nothing else.

Compare ONLY the following fields:
{deal_breakers_str}

GROUND TRUTH:
{json.dumps(gt_data, indent=2)}

EXTRACTED OUTPUT:
{json.dumps(output_data, indent=2)}

Comparison Rules:
1.  Strict, character-by-character comparison.
2.  EXCEPTIONS: case-insensitivity and leading/trailing whitespace are a Match.
3.  Any other difference is a Mismatch (e.g. currency symbols, commas).

JSON Output Structure:
{{
  "overall_status": "Pass" or "Mismatch",
  "mismatches": [{{ "field": "...", "expected": "...", "actual": "..." }}]
}}
If status is "Pass", mismatches must be an empty list.
Provide your verdict now.
"""
