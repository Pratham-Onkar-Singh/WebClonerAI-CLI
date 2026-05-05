# Website Cloner Agent

A conversational CLI AI agent that clones websites using the ReAct (Reasoning and Acting) framework. Built for Assignment 02 of the GenAI Class.

## Features
- **Conversational CLI**: Interact with the agent naturally.
- **ReAct Framework**: Transparent reasoning process (Think -> Action -> Observe).
- **Tool Use**: Fetches live website content, writes files, and executes shell commands.
- **Groq Integration**: Powered by Llama 3.3 70B for fast and accurate reasoning.
- **Rich UI**: Beautiful terminal output with colors and panels.

## Project Structure
- `agent.py`: Main entry point and ReAct reasoning engine.
- `prompt_config.py`: System instructions, goals, and few-shot examples.
- `tools.py`: Functional tools (Fetch, Write, Shell).
- `.env`: Environment variables (API Keys).

## Setup
1. **Install Dependencies**:
   ```bash
   pip install openai requests python-dotenv rich
   ```
2. **Configure API Key**:
   Ensure your `.env` file contains:
   ```env
   GROQ_API_KEY=your_key_here
   ```
3. **Run the Agent**:
   ```bash
   python agent.py
   ```

## Workflow
When you ask the agent to "Clone the Scaler Academy website", it will:
1. **Fetch** the HTML from `https://www.scaler.com/`.
2. **Analyze** the structure for Header, Hero, and Footer.
3. **Generate** and **Write** the corresponding HTML/CSS into `index.html`.
4. **Finalize** the output once the clone is complete.
