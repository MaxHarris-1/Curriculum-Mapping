# Free Data Analysis

A web application that provides instant analysis of various file types using AI. Supports CSV, Excel (XLSX), PDF, and text files.

## Features

- File upload via drag & drop or button click
- Support for multiple file formats (CSV, XLSX, PDF, TXT)
- AI-powered analysis using OpenAI's GPT models
- Dark/Light theme toggle
- Responsive design
- Clean, modern UI

## Setup

1. Clone the repository:
```bash
git clone https://github.com/maxharris1/FreeDataAnalysis.git
cd FreeDataAnalysis
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
```
Then edit `.env` and add your OpenAI API key.

4. Run the application:
```bash
python app.py
```

The application will be available at `http://localhost:5000`

## Environment Variables

- `OPENAI_API_KEY`: Your OpenAI API key (required)
- `OPENAI_ASSISTANT_ID`: ID of the OpenAI Assistant trained with the product catalog and OSHA standards (required)

## Security Note

Never commit your actual API keys to the repository. Always use environment variables for sensitive data. 