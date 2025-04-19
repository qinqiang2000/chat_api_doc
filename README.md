# OpenAI Assistant Chat App

A Streamlit application that allows you to chat with an OpenAI Assistant.

## Setup

1. Create a virtual environment (recommended):
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the assistant_app directory with your OpenAI API key:
```
OPENAI_API_KEY=your_api_key_here
```

## Running the App

To run the app, execute:
```bash
streamlit run app.py
```

The app will open in your default web browser. You can start chatting with the OpenAI Assistant by typing in the chat input box at the bottom of the page.

## Features

- Real-time chat interface
- Persistent chat history during the session
- Integration with OpenAI Assistant API
- Clean and modern UI 