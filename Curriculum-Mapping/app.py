import os
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from openai import OpenAI
import mimetypes
import pandas as pd
import time
from io import StringIO, BytesIO
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import mimetypes
import pandas as pd
import time
from io import StringIO
from PyPDF2 import PdfReader
import requests
import docx2txt
import tiktoken

print("Starting application...")

def cleanup_old_files():
    """Clean up any files that couldn't be deleted in previous sessions"""
    cleanup_file = 'cleanup.txt'
    if os.path.exists(cleanup_file):
        try:
            with open(cleanup_file, 'r') as f:
                files_to_cleanup = f.readlines()
            
            # Remove the cleanup file first
            os.remove(cleanup_file)
            
            # Try to remove each file
            for file_path in files_to_cleanup:
                file_path = file_path.strip()
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        print(f"Cleaned up old file: {file_path}")
                    except Exception as e:
                        print(f"Failed to clean up {file_path}: {str(e)}")
        except Exception as e:
            print(f"Error during cleanup: {str(e)}")

# Run cleanup on startup
cleanup_old_files()

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__, static_url_path='', static_folder='static')
CORS(app)  # Enable CORS for all routes
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'

# API Configuration
API_KEY = os.getenv('OPENAI_API_KEY')
if not API_KEY:
    print("Warning: OPENAI_API_KEY not found in environment variables")

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize OpenAI client
try:
    client = OpenAI(api_key=API_KEY)
    print("OpenAI API key set successfully")
    
    # Validate assistant access on startup
    default_assistant_id = "asst_LXN1PVzbBJ5HSZ5jJNJRynuJ"
    try:
        print(f"\nValidating access to assistant {default_assistant_id}...")
        assistant = client.beta.assistants.retrieve(default_assistant_id)
        print(f"Successfully connected to assistant: {assistant.name}")
    except Exception as e:
        print(f"\nWarning: Could not access the default assistant: {str(e)}")
        if "403" in str(e):
            print("\nPermission denied. Please check:")
            print("1. Your OpenAI API key has access to the Assistants API")
            print("2. You have permission to access this assistant")
            print("3. The assistant ID is correct")
        
except Exception as e:
    print(f"Error setting OpenAI API key: {str(e)}")
    raise

# Function to get organization ID from API key
def get_organization_id():
    try:
        # Try to make a simple request to get organization info
        models = client.models.list()
        # If successful, get the organization ID from the response headers
        if hasattr(models, 'headers') and 'x-organization-id' in models.headers:
            return models.headers['x-organization-id']
    except Exception as e:
        error_message = str(e)
        if 'mismatched_organization' in error_message:
            # Extract organization ID from error message if possible
            import re
            match = re.search(r'org-[a-zA-Z0-9]+', error_message)
            if match:
                return match.group(0)
    return None

# Get the correct organization ID
org_id = get_organization_id()
if org_id:
    print(f"Found organization ID: {org_id}")
    client.organization = org_id
else:
    print("Warning: Could not determine organization ID")

# Validate API key on startup
try:
    models = client.models.list()
    print("\nOpenAI API Configuration:")
    print(f"API Key Type: Project-scoped")
    print(f"Organization ID: {org_id}")
    print("\nAPI connection successful")
    print("Available models:", [model.id for model in models.data])
except Exception as e:
    print("\nAPI Key Validation Error:")
    print("Error type:", type(e).__name__)
    print("Error message:", str(e))
    if hasattr(e, 'response'):
        print("Status code:", getattr(e.response, 'status_code', None))
        print("Headers:", getattr(e.response, 'headers', None))
        try:
            print("Content:", getattr(e.response, 'content', None))
        except:
            print("Content: Unable to read response content")

def truncate_content(content, max_chars=4000):
    """Truncate content to avoid token limits"""
    if len(content) > max_chars:
        return content[:max_chars] + "\n[Content truncated due to length...]"
    return content

def call_openai_with_retry(messages, max_retries=3):
    """Call OpenAI API with retry logic"""
    for attempt in range(max_retries):
        try:
            print(f"\nOpenAI API Request (Attempt {attempt + 1}/{max_retries}):")
            print(f"Model: gpt-4")
            print(f"Message length: {len(str(messages))} characters")
            
            response = client.chat.completions.create(
                model="gpt-4",
                messages=messages,
                max_tokens=1000,  # Limit response tokens
                temperature=0.7
            )
            print("OpenAI Response received successfully")
            return response.choices[0].message.content
        except Exception as e:
            print(f"OpenAI API Error (Attempt {attempt + 1}/{max_retries}): {str(e)}")
            error_message = str(e)
            
            # Check for specific error types
            if "insufficient_quota" in error_message or "exceeded your current quota" in error_message:
                print("Usage limit error detected")
                if attempt < max_retries - 1:
                    print("Waiting before retry...")
                    time.sleep(1)  # Wait before retry
                    continue
            elif "invalid_api_key" in error_message or "mismatched_organization" in error_message:
                print("Authentication error detected")
                raise e
            elif "model_not_found" in error_message:
                print("Model not found, trying fallback model...")
                # Try with a different model if gpt-4 is not available
                try:
                    print("Using fallback model: gpt-3.5-turbo-16k")
                    response = client.chat.completions.create(
                        model="gpt-3.5-turbo-16k",  # Fallback model
                        messages=messages,
                        max_tokens=1000,
                        temperature=0.7
                    )
                    print("Fallback model response received successfully")
                    return response.choices[0].message.content
                except Exception as fallback_error:
                    print(f"Fallback model error: {str(fallback_error)}")
                    pass  # If fallback fails, continue with the retry loop
            
            # If we've exhausted all retries, raise the last error
            if attempt == max_retries - 1:
                print("All retry attempts exhausted")
                raise e
            
            print(f"Waiting before retry attempt {attempt + 2}...")
            time.sleep(1)

def is_valid_file(filename):
    # Check if file extension is .csv, .txt, .pdf, .xlsx, or .docx
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'csv', 'txt', 'pdf', 'xlsx', 'docx'}

def read_pdf_file(filepath):
    try:
        # Create a PDF reader object
        reader = PdfReader(filepath)
        
        # Extract text from all pages
        text = []
        text.append("PDF File Analysis:")
        text.append(f"\nTotal Pages: {len(reader.pages)}")
        
        # Extract text from each page
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text.strip():  # Only add non-empty pages
                text.append(f"\n--- Page {i+1} ---")
                text.append(page_text.strip())
        
        # Join all text parts
        return "\n".join(text)
    except Exception as e:
        print(f"Error reading PDF file: {str(e)}")
        return f"Error processing PDF: {str(e)}"

def read_excel_file(filepath):
    try:
        # Read Excel file with pandas
        xl = None
        df = None
        summary = []
        
        try:
            # Read the Excel file
            xl = pd.ExcelFile(filepath)
            sheet_names = xl.sheet_names
            
            # Format the data
            summary.append("Excel File Analysis:")
            summary.append(f"\nSheets in workbook: {', '.join(sheet_names)}")
            
            # Read the first sheet
            df = xl.parse(sheet_names[0])
            
            # Analyze active sheet
            summary.append(f"\nActive Sheet Analysis:")
            summary.append(f"\nColumn Names: {', '.join(df.columns.tolist())}")
            
            summary.append("\nData Preview (First 5 rows):")
            summary.append(df.head().to_string())
            
            summary.append("\nBasic Statistics:")
            summary.append(df.describe().to_string())
            
            summary.append("\nData Info:")
            buffer = StringIO()
            df.info(buf=buffer)
            summary.append(buffer.getvalue())
            buffer.close()
            
            return "\n".join(summary)
            
        finally:
            # Ensure we close all file handles
            if xl is not None:
                xl.close()
            # Force garbage collection of DataFrame to release file handle
            if df is not None:
                del df
            
    except Exception as e:
        print(f"Error reading Excel file: {str(e)}")
        return f"Error processing Excel file: {str(e)}"

def read_docx_file(filepath):
    try:
        # Extract text from the DOCX file
        text = docx2txt.process(filepath)
        
        # Format the output
        summary = []
        summary.append("Word Document Analysis:")
        summary.append("\nDocument Content:")
        summary.append(text.strip())
        
        return "\n".join(summary)
    except Exception as e:
        print(f"Error reading DOCX file: {str(e)}")
        return f"Error processing DOCX: {str(e)}"

def read_and_format_file(filepath):
    file_ext = filepath.rsplit('.', 1)[1].lower()
    
    if file_ext == 'pdf':
        return read_pdf_file(filepath)
    elif file_ext == 'xlsx':
        return read_excel_file(filepath)
    elif file_ext == 'csv':
        try:
            # Try reading with pandas default engine
            df = pd.read_csv(filepath, encoding_errors='replace')
        except Exception as e:
            try:
                # Try reading with python engine which is more forgiving
                df = pd.read_csv(filepath, encoding_errors='replace', engine='python')
            except Exception as e:
                print(f"Error reading CSV with python engine: {str(e)}")
                return read_text_file(filepath)

        try:
            # Format the data
            summary = []
            summary.append("CSV File Analysis:")
            summary.append(f"\nColumn Names: {', '.join(df.columns.tolist())}")
            
            summary.append("\nData Preview (First 5 rows):")
            summary.append(df.head().to_string())
            
            summary.append("\nBasic Statistics:")
            summary.append(df.describe().to_string())
            
            summary.append("\nData Info:")
            buffer = StringIO()
            df.info(buf=buffer)
            summary.append(buffer.getvalue())
            buffer.close()
            
            return "\n".join(summary)
        except Exception as e:
            print(f"Error formatting CSV data: {str(e)}")
            # If formatting fails, return raw text
            return df.to_string()
    elif file_ext == 'docx':
        return read_docx_file(filepath)
    else:
        return read_text_file(filepath)

def read_text_file(filepath):
    try:
        # Try reading with default encoding
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except Exception as e:
        print(f"Error reading text file: {str(e)}")
        # If all else fails, try binary read and decode
        with open(filepath, 'rb') as f:
            return f.read().decode('utf-8', errors='replace')

def check_api_quota():
    """Check if the API key has available quota"""
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=1
        )
        return True
    except Exception as e:
        error_message = str(e)
        if "insufficient_quota" in error_message or "exceeded your current quota" in error_message:
            return False
        raise e

def get_data_analysis_prompt(file_content):
    """Prompt for analyzing tabular data (CSV, XLSX)"""
    return f"""You are a senior data analyst. Please provide a comprehensive analysis of the dataset in the following format:

1. Executive Summary (2-3 paragraphs):
   - Provide a high-level overview of what the dataset contains
   - Highlight the most interesting and significant findings
   - Discuss key patterns, trends, and relationships discovered
   - Emphasize practical implications and insights
   - Note any significant limitations or considerations

2. Statistical Overview:
   A. Dataset Dimensions
   - Total number of records
   - Number of variables
   - Data completeness metrics
   
   B. Numerical Variables
   - List each numerical variable with:
     * Mean, median, standard deviation
     * Range (min, max)
     * Distribution characteristics
     * Notable outliers
   
   C. Categorical Variables
   - List each categorical variable with:
     * Frequency distribution
     * Mode and unique values count
     * Missing value percentage

3. Key Relationships:
   - List the strongest correlations found
   - Describe any notable patterns
   - Highlight unexpected findings

4. Recommended Visualizations:
   For each suggested visualization, provide:
   - Type of plot (e.g., scatter plot, bar chart, etc.)
   - Variables to include
   - Purpose of the visualization
   - Key insights it would reveal
   Example format:
   1. [Plot Type]: [Variables] - [Purpose]
   2. [Plot Type]: [Variables] - [Purpose]

5. Action Items:
   - List 3-5 concrete recommendations
   - Include specific metrics to track
   - Suggest next steps for deeper analysis

Here's the data to analyze:

{file_content}"""

def get_text_analysis_prompt(file_content):
    """Prompt for analyzing text documents (TXT, PDF)"""
    return f"""You are a senior content analyst. Please provide a clear and practical summary of this document in the following format:

1. Executive Summary (2-3 paragraphs):
   - Provide a clear, concise overview of what this document is about
   - Highlight the main purpose and key points
   - Identify who this document is for and why it matters

2. Key Information:
   - Main topics covered
   - Important dates or deadlines (if any)
   - Key people, organizations, or entities mentioned
   - Critical numbers or statistics (if any)
   - Important definitions or terms explained

3. Instructions or Action Items (if present):
   [Include this section only if the document contains instructions or required actions]
   - List all instructions or required actions clearly
   - Specify any step-by-step processes
   - Note any deadlines or time-sensitive items
   - Highlight any requirements or prerequisites
   - List any warnings or important cautions

4. Important Details:
   - List any significant findings or conclusions
   - Note any crucial requirements or conditions
   - Highlight any exceptions or special cases
   - Include any relevant contact information or resources

5. Additional Notes:
   - Any supplementary information that might be useful
   - References to other documents or resources
   - Potential next steps or follow-up actions
   - Questions that might need clarification

Please format your response using clear headings and maintain readability with appropriate spacing. Use bullet points for lists and highlight particularly important information. If certain sections are not applicable to this document, you may skip them.

Here's the text to analyze:

{file_content}"""

# Ollama configuration
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_MODELS = ["llama3.2:latest", "deepseek-r1:8b"]

def call_ollama(prompt, model="llama3.2:latest"):
    """Call the local Ollama instance"""
    try:
        print(f"\nOllama Request:")
        print(f"Model: {model}")
        print(f"Prompt length: {len(prompt)} characters")
        
        # Map frontend model names to actual Ollama model names
        model_mapping = {
            "llama": "llama3.2:latest",
            "deepseek": "deepseek-r1:8b"
        }
        
        actual_model = model_mapping.get(model, model)
        
        response = requests.post(OLLAMA_API_URL, json={
            "model": actual_model,
            "prompt": prompt,
            "stream": False
        })
        response.raise_for_status()
        
        print("Ollama Response Status:", response.status_code)
        return response.json()['response']
    except requests.RequestException as e:
        print(f"\nOllama Error Details:")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        if hasattr(e, 'response'):
            print(f"Status code: {getattr(e.response, 'status_code', None)}")
            print(f"Response content: {getattr(e.response, 'content', None)}")
        raise Exception("Error connecting to local LLM. Please ensure Ollama is running.") from e

def call_openai_assistant(prompt, assistant_id="asst_LXN1PVzbBJ5HSZ5jJNJRynuJ"):
    """Call OpenAI Assistant API with the curriculum mapping assistant"""
    try:
        print(f"\nCreating thread with Assistant {assistant_id}")
        try:
            thread = client.beta.threads.create()
        except Exception as e:
            print(f"Error creating thread: {str(e)}")
            if "403" in str(e):
                print("Permission denied. Please check your OpenAI API key and organization settings.")
            raise e
        
        print("Thread created successfully, adding message...")
        try:
            # Add the message to the thread
            message = client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=prompt
            )
        except Exception as e:
            print(f"Error creating message: {str(e)}")
            raise e
        
        print("Message added successfully, running assistant...")
        try:
            # Run the assistant
            run = client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=assistant_id
            )
        except Exception as e:
            print(f"Error starting assistant run: {str(e)}")
            if "403" in str(e):
                print("Permission denied. Please verify the assistant ID and your access to it.")
            raise e
        
        print("Assistant run started, waiting for completion...")
        # Poll for completion
        while True:
            try:
                run_status = client.beta.threads.runs.retrieve(
                    thread_id=thread.id,
                    run_id=run.id
                )
                if run_status.status == 'completed':
                    break
                elif run_status.status == 'failed':
                    error_msg = getattr(run_status, 'last_error', 'Unknown error')
                    raise Exception(f"Assistant run failed: {error_msg}")
                time.sleep(1)  # Wait before checking again
            except Exception as e:
                print(f"Error checking run status: {str(e)}")
                raise e
        
        print("Run completed, retrieving messages...")
        try:
            # Get the assistant's response
            messages = client.beta.threads.messages.list(thread_id=thread.id)
            # Get the last assistant message
            for msg in messages:
                if msg.role == "assistant":
                    return msg.content[0].text.value
        except Exception as e:
            print(f"Error retrieving messages: {str(e)}")
            raise e
                
        return "No response from assistant"
        
    except Exception as e:
        print(f"Error calling OpenAI Assistant: {str(e)}")
        if "403" in str(e):
            print("\nThis appears to be a permissions error. Please check:")
            print("1. Your OpenAI API key is valid")
            print("2. Your organization ID is correct")
            print("3. You have access to the assistant ID:", assistant_id)
            print("4. Your API key has permission to use the Assistants API")
        raise e

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/test-ollama')
def test_ollama():
    """Test endpoint to verify Ollama connectivity"""
    try:
        print("\nTesting Ollama connection...")
        # First check if Ollama is running
        try:
            print("Checking Ollama server status...")
            response = requests.get("http://localhost:11434/api/tags")
            response.raise_for_status()
            models = response.json()
            print("Available models:", models)
            
            # Test if llama3.2 is available
            if not any(model.get('name') == 'llama3.2' for model in models.get('models', [])):
                print("llama3.2 model not found")
                return jsonify({
                    'status': 'warning',
                    'message': 'Ollama is running but llama3.2 model is not found. Please run: ollama pull llama3.2'
                }), 200
        except requests.RequestException as e:
            print(f"Ollama server connection error: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': 'Ollama server is not running. Please start it with: ollama serve',
                'error': str(e)
            }), 503

        # Test model with a simple prompt
        print("Testing model with simple prompt...")
        test_response = call_ollama("Hello, are you working?")
        print(f"Test response received: {test_response}")
        
        return jsonify({
            'status': 'success',
            'message': 'Ollama is running and responding correctly',
            'test_response': test_response
        }), 200
        
    except Exception as e:
        print(f"Unexpected error during Ollama test: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Error testing Ollama',
            'error': str(e)
        }), 500

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not is_valid_file(file.filename):
            return jsonify({'error': 'Please upload a Word (DOCX), CSV, Excel, text, or PDF file'}), 400
        
        # Save the file
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            # Read the file content based on its type
            file_extension = filename.rsplit('.', 1)[1].lower()
            if file_extension == 'pdf':
                content = read_pdf_file(filepath)
            elif file_extension == 'xlsx':
                content = read_excel_file(filepath)
            elif file_extension == 'docx':
                content = read_docx_file(filepath)
            else:  # txt or csv
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
            
            # Truncate content if necessary
            content = truncate_content(content)
            
            # Prepare the message for analysis
            messages = [
                {"role": "system", "content": "You are a helpful assistant that analyzes documents and provides insights."},
                {"role": "user", "content": f"Please analyze this document and provide insights:\n\n{content}"}
            ]
            
            # Get selected model
            model_type = request.form.get('model_type', 'openai')  # Default to OpenAI
            
            # Process based on model type
            if model_type == 'openai':
                analysis = call_openai_with_retry(messages)
            elif model_type == 'llama':
                analysis = call_ollama(messages, "llama3.2:latest")
            elif model_type == 'deepseek':
                analysis = call_ollama(messages, "deepseek-r1:8b")
            else:
                return jsonify({'error': 'Invalid model type selected'}), 400
            
            return jsonify({'analysis': analysis})
            
        finally:
            # Clean up the uploaded file
            try:
                os.remove(filepath)
            except Exception as e:
                print(f"Error removing file: {str(e)}")
                with open('cleanup.txt', 'a') as f:
                    f.write(f"{filepath}\n")
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/check-ollama-status')
def check_ollama_status():
    """Proxy endpoint to check Ollama status and OpenAI status"""
    try:
        # Check Ollama status
        try:
            response = requests.get("http://localhost:11434/api/tags")
            response.raise_for_status()
            models = response.json()
            print("Available Ollama models:", models)
            
            # Get available local models
            available_models = [
                model.get('name', '') 
                for model in models.get('models', [])
            ]
            
            # Update model checking logic to match exact model names
            local_models = {
                'llama': any('llama3.2' in m for m in available_models),
                'deepseek': any('deepseek-r1:8b' == m for m in available_models)
            }
            
            print("Detected models:", local_models)  # Debug print
            ollama_online = True
        except requests.RequestException as e:
            print(f"Ollama connection error: {str(e)}")
            ollama_online = False
            local_models = {'llama': False, 'deepseek': False}

        # Check OpenAI status
        try:
            assistant = client.beta.assistants.retrieve("asst_LXN1PVzbBJ5HSZ5jJNJRynuJ")
            openai_online = True
        except Exception:
            openai_online = False

        response = jsonify({
            'status': 'success',
            'models': {
                'openai': {
                    'available': openai_online,
                    'name': 'OpenAI Assistant'
                },
                'llama': {
                    'available': local_models['llama'],
                    'name': 'Llama 3.2'
                },
                'deepseek': {
                    'available': local_models['deepseek'],
                    'name': 'Deepseek-r1 8B'
                }
            },
            'message': 'Model status retrieved successfully'
        })
        
        # Add CORS headers
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET')
        return response
        
    except Exception as e:
        print(f"Error in check-ollama-status: {str(e)}")  # Debug print
        error_response = jsonify({
            'status': 'error',
            'message': str(e)
        })
        error_response.headers.add('Access-Control-Allow-Origin', '*')
        error_response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        error_response.headers.add('Access-Control-Allow-Methods', 'GET')
        return error_response, 500

def load_reference_data():
    """Load and format the product catalog and OSHA standards data"""
    try:
        # Load Product Catalog
        reader = PdfReader("Transfr_Product_Catalog_May2024 (8).pdf")
        catalog_text = ""
        for page in reader.pages:
            catalog_text += page.extract_text() + "\n"

        # Load OSHA Standards
        standards_df = pd.read_csv("OSHA Sims - 76S 22H46M.csv")
        standards_text = standards_df.to_string()

        return catalog_text, standards_text
    except Exception as e:
        print(f"Error loading reference data: {str(e)}")
        return None, None

def construct_gpt_prompt(form_data, course_outline_text):
    """Construct the GPT-4 prompt with all necessary components"""
    
    # Part 1: Initial Prompt
    initial_prompt = """CRITICAL INSTRUCTION: You must ONLY suggest simulations that exist in the Transfr Product Catalog. DO NOT invent, create, or suggest any simulations that are not explicitly listed in the catalog.

This prompt is structured in three parts:
1. This initial explanation
2. The customer data and requirements
3. Detailed instructions for processing and output format

Please process the following information according to the instructions provided in part 3."""

    # Part 2: Data Section
    data_section = f"""
CUSTOMER DATA
------------
Grade Level: {form_data['grade_level']}
State: {form_data['state']}
Instruction Type: {form_data['instruction_type']}

COURSE OUTLINE
-------------
{course_outline_text}

ADDITIONAL INFORMATION
--------------------
Relevant Standards: {form_data.get('relevant_standards', 'None provided')}
Special Requests: {form_data.get('special_requests', 'None provided')}"""

    # Part 3: Instructions with enhanced emphasis on catalog-only simulations
    instructions_section = """
INSTRUCTIONS
-----------
CRITICAL RULES FOR SIMULATION MATCHING:
1. ONLY suggest simulations that are explicitly listed in the Transfr Product Catalog
2. NEVER create, invent, or suggest simulations that don't exist in the catalog
3. If you cannot find a matching simulation in the catalog, state "No matching simulation found in catalog" for that section
4. All simulation titles and descriptions MUST be copied exactly as they appear in the catalog
5. If unsure about a simulation's existence, err on the side of caution and do not include it

Input Analysis:
- Review the provided course outline or objectives
- If there are special requests present in the input, address them using ONLY catalog simulations
- If there are standards present in the input, match them with ONLY catalog simulations

Simulation Matching Process:
1. First, verify each simulation exists in the product catalog
2. Only after verification, match it based on:
   - Career pathways alignment
   - Skill requirements match
   - Time and resource constraints
3. If no exact match exists, clearly state this rather than suggesting a non-catalog simulation

Summary Creation:
- Provide a clear summary including:
  - ONLY verified simulation titles and descriptions from the product catalog
  - Total number of VERIFIED simulations (in bold)
  - Relevant OSHA standards covered by the VERIFIED simulations
  - Estimated total headset time based on VERIFIED simulations

Output Format:
Generate a structured response with consistent indentation and text wrapping. Use this exact format:

Customer Name: [Insert Name]

Course Outline Summary:
[Summarized Input]

Matched Simulations by Section:
[Section Name or Week]
    Simulation: [VERIFIED Title from Catalog]
    Description: [EXACT Description from Catalog]
    Duration: [X Minutes]
    
[Next Section/Week]
[Continue format for each section]
[If no matching simulation found, state "No matching simulation found in catalog"]

Summary:
Total Number of Simulations: [X]
Total Headset Time: [X Hours, X Minutes]
Relevant OSHA Standards: [List of Standards]

IMPORTANT FORMATTING RULES:
1. Use consistent indentation (4 spaces) for all simulation details
2. Do not use manual line breaks within descriptions
3. Let text wrap naturally within the width of the display
4. Maintain the exact spacing shown above between sections
5. Keep all text left-aligned within their respective indentation levels
6. Do not use any special formatting characters or markdown
7. Ensure each simulation entry follows the exact same format and spacing

FINAL VERIFICATION:
Before submitting your response, verify one final time that:
1. Every single simulation listed exists in the product catalog
2. All descriptions match the catalog exactly
3. No simulations have been invented or modified
4. Sections without matching catalog simulations are clearly marked"""

    # Combine all sections with clear separators
    full_prompt = f"{initial_prompt}\n\n{'='*50}\n\n{data_section}\n\n{'='*50}\n\n{instructions_section}"
    
    return full_prompt

@app.route('/curriculum-mapping', methods=['GET'])
def curriculum_mapping_form():
    return render_template('curriculum_mapping.html')

def read_file_content(file):
    """Read file content with support for PDF and Word documents"""
    file_ext = file.filename.lower().split('.')[-1] if '.' in file.filename else ''
    
    print(f"Reading file: {file.filename} with extension: {file_ext}")

    try:
        if file_ext == 'pdf':
            # Handle PDF files
            pdf_reader = PdfReader(file)
            content = ""
            for page in pdf_reader.pages:
                page_text = page.extract_text()
                print(f"Extracted text from page: {page_text[:100]}...")  # Debugging
                content += page_text + "\n"
            print(f"Total extracted content length: {len(content)} characters")  # Debugging
            return content
            
        elif file_ext in ['doc', 'docx']:
            # Handle Word documents
            content = docx2txt.process(file)
            print(f"Extracted text from Word document: {content[:100]}...")  # Debugging
            print(f"Total extracted content length: {len(content)} characters")  # Debugging
            return content
            
        else:
            # Try different text encodings for other file types
            try:
                content = file.read().decode('utf-8')
                print(f"Extracted text with utf-8: {content[:100]}...")  # Debugging
            except UnicodeDecodeError:
                file.seek(0)
                try:
                    content = file.read().decode('latin-1')
                    print(f"Extracted text with latin-1: {content[:100]}...")  # Debugging
                except UnicodeDecodeError:
                    file.seek(0)
                    content = file.read().decode('cp1252')
                    print(f"Extracted text with cp1252: {content[:100]}...")  # Debugging
            print(f"Total extracted content length: {len(content)} characters")  # Debugging
            return content
            
    except Exception as e:
        raise Exception(f"Error reading file: {str(e)}. Please ensure the file is in PDF, Word, or text format.")

# Function to estimate token count

def estimate_token_count(text):
    tokenizer = tiktoken.get_encoding("cl100k_base")
    tokens = tokenizer.encode(text)
    return len(tokens)

@app.route('/map_curriculum', methods=['POST'])
def map_curriculum():
    try:
        # Get form data
        form_data = {
            'grade_level': request.form.get('grade_level'),
            'state': request.form.get('state'),
            'instruction_type': request.form.getlist('instruction_type'),  # Get all selected values
            'relevant_standards': request.form.get('relevant_standards', ''),
            'special_requests': request.form.get('special_requests', '')
        }

        # Join multiple instruction types with commas
        form_data['instruction_type'] = ', '.join(form_data['instruction_type'])

        # Process the course outline file
        if 'course_outline' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['course_outline']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not is_valid_file(file.filename):
            return jsonify({'error': 'Please upload a CSV, Excel, text, or PDF file'}), 400

        # Save and process the file
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        try:
            # Read the course outline
            course_outline_text = read_and_format_file(filepath)
            
            # Construct the prompt
            prompt = construct_gpt_prompt(form_data, course_outline_text)
            
            # Get response from OpenAI Assistant
            # Use environment variable if set, otherwise use default
            assistant_id = os.getenv('OPENAI_ASSISTANT_ID', "asst_LXN1PVzbBJ5HSZ5jJNJRynuJ")
            result = call_openai_assistant(prompt, assistant_id)
            
            return jsonify({'result': result})
            
        finally:
            # Clean up the uploaded file
            try:
                os.remove(filepath)
            except Exception as e:
                print(f"Error removing file: {str(e)}")
                with open('cleanup.txt', 'a') as f:
                    f.write(f"{filepath}\n")
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/estimate-tokens', methods=['POST'])
def estimate_tokens():
    try:
        # Get form data
        form_data = {
            'grade_level': request.form.get('grade_level', ''),
            'state': request.form.get('state', ''),
            'instruction_type': request.form.getlist('instruction_type'),
            'relevant_standards': request.form.get('relevant_standards', ''),
            'special_requests': request.form.get('special_requests', '')
        }

        # Process course outline file
        if 'course_outline' not in request.files:
            return jsonify({'error': 'No course outline file provided'}), 400
        
        file = request.files['course_outline']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        # Read course outline content
        try:
            course_outline_text = read_and_format_file(file.filename)
        except Exception as e:
            return jsonify({'error': str(e)}), 400

        # Define base prompt
        base_prompt = """You are a curriculum mapping expert for Transfr VR training simulations. 
Your task is to analyze the provided course outline and identify relevant Transfr VR simulations that could enhance the training.

Please format your response as follows:

Course Overview:
[Brief summary of the course content and objectives]

Relevant Transfr VR Simulations:
[List identified simulations, grouped by course topic/module]

Additional Recommendations:
[Suggestions for maximizing VR simulation integration]"""

        # Convert form data to string for token counting
        form_text = f"""
Grade Level: {form_data['grade_level']}
State: {form_data['state']}
Instruction Type: {', '.join(form_data['instruction_type'])}
Relevant Standards: {form_data['relevant_standards']}
Special Requests: {form_data['special_requests']}
"""

        # Estimate token counts
        outline_tokens = estimate_token_count(course_outline_text)
        form_tokens = estimate_token_count(form_text)
        base_tokens = estimate_token_count(base_prompt)

        return jsonify({
            'outline_tokens': outline_tokens,
            'form_tokens': form_tokens,
            'base_tokens': base_tokens
        })

    except Exception as e:
        print(f"Error in /estimate-tokens: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/export-pdf', methods=['POST'])
def export_pdf():
    try:
        content = request.json.get('content')
        if not content:
            return jsonify({'error': 'No content provided'}), 400

        # Create a PDF buffer
        buffer = BytesIO()
        
        # Create the PDF with reportlab
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        y = height - 40  # Start near the top of the page
        
        # Split content into lines and write to PDF
        for line in content.split('\n'):
            # If the line would go below the bottom margin, start a new page
            if y < 40:
                c.showPage()
                y = height - 40
            
            # Write the line
            c.drawString(40, y, line)
            y -= 15  # Move down for next line
        
        c.save()
        
        # Move buffer position to start
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name='curriculum_mapping.pdf',
            mimetype='application/pdf'
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/export-excel', methods=['POST'])
def export_excel():
    try:
        content = request.json.get('content')
        if not content:
            return jsonify({'error': 'No content provided'}), 400

        # Create a pandas DataFrame from the content
        # Split content into sections
        sections = content.split('\n\n')
        data = []
        current_section = ''
        
        for section in sections:
            lines = section.strip().split('\n')
            if lines[0].endswith(':'):  # This is a section header
                current_section = lines[0].rstrip(':')
            else:
                for line in lines:
                    if line.strip():
                        data.append({
                            'Section': current_section,
                            'Content': line
                        })

        df = pd.DataFrame(data)
        
        # Create Excel file in memory
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Curriculum Mapping')
        
        excel_buffer.seek(0)
        
        return send_file(
            excel_buffer,
            as_attachment=True,
            download_name='curriculum_mapping.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                             'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

if __name__ == '__main__':
    print("Starting Flask server on port 5002...")
    app.run(host='0.0.0.0', debug=True, port=5002)
