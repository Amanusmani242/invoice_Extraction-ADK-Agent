# invoice_agent/agent.py
import os
from dotenv import load_dotenv

# Load environment variables from the root project directory
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=dotenv_path)

# Correctly import the Agent class and configure Gemini
import google.generativeai as genai
from google.adk.agents import Agent

# Import our tools and the high-level agent instruction
from .tools.pipeline_utils import (
    setup_gcs_folders,
    route_invoices,
    extract_data,
    evaluate_extractions,
)
from .prompts import AGENT_INSTRUCTION

# --- AGENT CONFIGURATION & DEFINITION ---

# Configure the API Key for the entire application
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Create the agent instance
root_agent = Agent(
    name="invoice_processing_agent",
    model="gemini-2.5-flash",
    description="An autonomous agent that automates the entire invoice lifecycle: routing, data extraction, and evaluation.",
    instruction=AGENT_INSTRUCTION,
    tools=[
        setup_gcs_folders,
        route_invoices,
        extract_data,
        evaluate_extractions,
    ],
)
