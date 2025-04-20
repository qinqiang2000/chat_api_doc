import streamlit as st
import openai
from openai import OpenAI
from openai import AssistantEventHandler
from typing_extensions import override
import os
from dotenv import load_dotenv
from sync import sync_assistant_files
from datetime import datetime
import yaml
import logging
from pathlib import Path
from streamlit_feedback import streamlit_feedback

# Set up logging
def setup_logging():
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Create log file with current date
    log_file = log_dir / f"chat_{datetime.now().strftime('%Y-%m-%d')}.log"
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

# Initialize logger
logger = setup_logging()

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), project="proj_jiG8eccaCUMs4uKfXqUouCeN")


# Load assistant configurations from YAML file
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config.get('assistants', {})

# Load assistants configuration
ASSISTANTS = load_config()

class StreamHandler(AssistantEventHandler):
    def __init__(self, message_placeholder):
        super().__init__()
        self.message_placeholder = message_placeholder
        self.full_response = ""
        
    @override
    def on_text_created(self, text) -> None:
        self.message_placeholder.markdown("")
        
    @override
    def on_text_delta(self, delta, snapshot):
        self.full_response += delta.value
        self.message_placeholder.markdown(self.full_response + "▌")
        
    def on_tool_call_created(self, tool_call):
        self.message_placeholder.markdown(f"\n{tool_call.type}\n")
        
    def on_tool_call_delta(self, delta, snapshot):
        if delta.type == 'code_interpreter':
            if delta.code_interpreter.input:
                self.message_placeholder.markdown(delta.code_interpreter.input)
            if delta.code_interpreter.outputs:
                for output in delta.code_interpreter.outputs:
                    if output.type == "logs":
                        self.message_placeholder.markdown(f"\n{output.logs}")

def handle_feedback(feedback):
    """Handle feedback from users"""
    feedback_type = feedback.get("type")
    score = feedback.get("score")
    text = feedback.get("text", "")
    logger.info(f"Received feedback - Type: {feedback_type}, Score: {score}, Text: {text}")

def main():
    # Get assistant type from URL parameters
    assistant_type = st.query_params.get("type")  # Default to ultimate if not specified
    sync = st.query_params.get("sync", "false").lower() == "true"
    
    # Validate assistant type
    if assistant_type not in ASSISTANTS:
        st.write("Hello")
        return  # Exit early if invalid type
        
    # Get assistant config
    assistant = ASSISTANTS[assistant_type]
    
    # Log assistant type and sync status
    logger.info(f"Session started with assistant type: {assistant_type}")

    # Handle file sync if requested
    if sync:
        logger.info("Syncing assistant files")
        sync_assistant_files(client, assistant)
        return

    # Initialize session state for this assistant
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "thread" not in st.session_state:
        st.session_state.thread = client.beta.threads.create()
        logger.info(f"New thread created with ID: {st.session_state.thread.id}")

    # Set page config
    st.set_page_config(
        page_title=assistant["title"],
        page_icon=assistant["icon"]
    )

    # Title and description
    st.title(f"{assistant['icon']} {assistant['title']}")
    st.caption(assistant["description"])

    # Display chat messages
    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            # Add feedback component for assistant messages
            if message["role"] == "assistant":
                streamlit_feedback(
                    feedback_type="thumbs",
                    key=f"feedback_{idx}",  # Add unique key based on message index
                    on_submit=handle_feedback
                )

    # Chat input
    prompt = st.chat_input("请输入您的问题...")
    if prompt:
        # Log user input
        logger.info(f"User input: {prompt}")
        
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Add message to thread
        client.beta.threads.messages.create(
            thread_id=st.session_state.thread.id,
            role="user",
            content=prompt
        )
        
        # Create a placeholder for the assistant's response
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            
            # Create event handler
            handler = StreamHandler(message_placeholder)
            
            # Stream the response
            with client.beta.threads.runs.stream(
                thread_id=st.session_state.thread.id,
                assistant_id=assistant["id"],
                event_handler=handler
            ) as stream:
                stream.until_done()
                
            # Remove the cursor
            message_placeholder.markdown(handler.full_response)
            
            # Add feedback component for the new response
            streamlit_feedback(
                feedback_type="thumbs",
                key=f"feedback_{len(st.session_state.messages)}",  # Add unique key based on new message index
                on_submit=handle_feedback
            )
            
            # Log assistant response
            logger.info(f"Assistant response: {handler.full_response}")
            
            # Add the complete response to chat history
            st.session_state.messages.append(
                {"role": "assistant", "content": handler.full_response}
            )

if __name__ == "__main__":
    main() 