import streamlit as st
import openai
from openai import OpenAI
from openai import AssistantEventHandler
from typing_extensions import override
import os
import logging
from dotenv import load_dotenv
from sync import sync_assistant_files
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

# Create formatter and add it to the handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)

# Add the handlers to the logger
logger.addHandler(ch)

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), project="proj_jiG8eccaCUMs4uKfXqUouCeN")

# Initialize scheduler
scheduler = BackgroundScheduler()
scheduler.start()

def sync_all_assistants():
    """Sync all assistants"""
    logger.info("Running daily sync for all assistants...")
    for assistant_type, assistant in ASSISTANTS.items():
        logger.info(f"Syncing {assistant_type} assistant...")
        sync_assistant_files(client, assistant)
    logger.info("Daily sync completed")

# Schedule sync task to run at 23:00 every day
scheduler.add_job(sync_all_assistants, 'cron', hour=22, minute=31)

# Assistant configurations
ASSISTANTS = {
    "standard": {
        "id": "asst_jeHiEoUgYxd2oOjxZyqIP4YR",  # 替换为标准版助手的 ID
        "title": "标准版API Chatbot",
        "icon": "🤖",
        "description": "🚀 A chatbot powered by 发票云",
        "llm_txt_url": "https://open-standard.piaozone.com/llms.txt"
    },
    "ultimate": {
        "id": "asst_TTZaGdtxROyACaoNCCSOigSw",  # 替换为旗舰版助手的 ID
        "title": "旗舰版API Chatbot",
        "icon": "🤖",
        "description": "🚀 A chatbot powered by 发票云",
        "llm_txt_url": "https://open.piaozone.com/llms.txt"
    }
}

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

    # Handle file sync if requested
    if sync:
        sync_assistant_files(client, assistant)
        return

    # Initialize session state for this assistant
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "thread" not in st.session_state:
        st.session_state.thread = client.beta.threads.create()

    # Set page config
    st.set_page_config(
        page_title=assistant["title"],
        page_icon=assistant["icon"]
    )

    # Title and description
    st.title(f"{assistant['icon']} {assistant['title']}")
    st.caption(assistant["description"])

    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat input
    prompt = st.chat_input("请输入您的问题...")
    if prompt:
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
            
            # Add the complete response to chat history
            st.session_state.messages.append(
                {"role": "assistant", "content": handler.full_response}
            )

if __name__ == "__main__":
    main() 