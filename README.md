# Invoice Processing Agent

This project implements an autonomous agent that automates the entire invoice lifecycle: routing, data extraction, and evaluation(using ADK Freamework).

## Setup

1.  **Install dependencies:**
    ```
    pip install -r requirements.txt
    ```
2.  **Create a `.env` file:**
    -   Copy the `.env.example` file to `.env`.
    -   Fill in the required environment variables:
        -   `GCP_PROJECT_ID`: Your Google Cloud project ID.
        -   `GCS_BUCKET_NAME`: The name of your GCS bucket.
        -   `GOOGLE_API_KEY`: Your Google API key for Gemini.

## Running the Agent

You can run the agent using the ADK CLI:
```
adk run invoice_agent
```

## Tools

The agent has the following tools available:

-   **`setup_gcs_folders(gcs_location: str)`**: Sets up the necessary folder structure in GCS if the provided location is empty.
-   **`route_invoices(gcs_location: str)`**: Routes invoices from the 'input_invoices' folder to vendor-specific folders.
-   **`extract_data(gcs_location: str)`**: Extracts data from invoices in the 'sorted_invoices' folder and saves it as JSON.
-   **`evaluate_extractions(gcs_location: str)`**: Evaluates the extracted invoice data against the ground truth and generates a report.
