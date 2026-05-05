import os
import json
from openai import OpenAI
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.text import Text

from tools import TOOL_MAP
from prompt_config import SYSTEM_PROMPT, FEW_SHOT_EXAMPLES

# Load environment variables
load_dotenv()

# Initialize Rich console for beautiful output
console = Console()

# Initialize Hugging Face Router client
client = OpenAI(
    api_key=os.getenv("HUGGINGFACE_API_KEY"),
    base_url="https://router.huggingface.co/v1"
)

import sys

def extract_first_json(text):
    """Extract the first valid JSON object from text (handles multiple JSON objects)."""
    # Find first opening brace
    start_idx = text.find('{')
    if start_idx == -1:
        raise json.JSONDecodeError("No JSON object found", text, 0)
    
    # Find matching closing brace
    brace_count = 0
    for i in range(start_idx, len(text)):
        if text[i] == '{':
            brace_count += 1
        elif text[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                # Found matching closing brace
                json_str = text[start_idx:i+1]
                return json.loads(json_str)
    
    raise json.JSONDecodeError("Unmatched braces in JSON", text, start_idx)

def main():
    console.print(Panel.fit("[bold blue]Website Cloner Agent[/bold blue]\n[italic]Powered ReAct Reasoning[/italic]", border_style="blue"))
    
    # Check for command line argument, otherwise ask for input
    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:])
        console.print(f"[bold green]User (via arg):[/bold green] {user_input}")
    else:
        user_input = console.input("[bold green]User:[/bold green] ")
    
    if not user_input:
        user_input = "Clone the Scaler Academy website."

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    # Add few-shot examples
    messages.extend(FEW_SHOT_EXAMPLES)
    # Add current user request
    messages.append({"role": "user", "content": user_input})

    retry_count = 0
    max_retries = 3
    
    while True:
        try:
            # Get completion from LLM
            response = client.chat.completions.create(
                # model="meta-llama/Meta-Llama-3-70B-Instruct",
                # model="meta-llama/Llama-3.3-70B-Instruct",
                model="MiniMaxAI/MiniMax-M2.7",
                messages=messages,
                temperature=0.2,
                max_tokens=30000,
                timeout=120
            )
            
            assistant_msg = response.choices[0].message.content
            
            # Check for empty response
            if not assistant_msg or not assistant_msg.strip():
                retry_count += 1
                if retry_count >= max_retries:
                    console.print(f"[bold red]✗ Max retries reached. Model is returning empty responses.[/bold red]")
                    break
                console.print(f"[bold yellow]⟳ Retry {retry_count}/{max_retries} (Empty Response)...[/bold yellow]")
                
                # Tell the LLM it failed so it corrects itself
                messages.append({
                    "role": "user", 
                    "content": "You returned an empty response. You MUST reply with a valid JSON object starting with '{'."
                })
                continue
            
            try:
                # Extract first valid JSON object
                parsed = extract_first_json(assistant_msg)
            except json.JSONDecodeError as e:
                retry_count += 1
                if retry_count >= max_retries:
                    console.print(f"[bold red]✗ Model returned invalid JSON repeatedly.[/bold red]")
                    console.print(f"[bold yellow]Last response:[/bold yellow] {assistant_msg[:200]}")
                    break
                console.print(f"[bold yellow]⟳ Retry {retry_count}/{max_retries} (invalid JSON)...[/bold yellow]")
                
                # Append the bad response and a correction prompt so it learns from the mistake
                messages.append({"role": "assistant", "content": assistant_msg})
                messages.append({
                    "role": "user", 
                    "content": "SYSTEM ERROR: Your previous response was not valid JSON. Do not output plain text lists or plans. You MUST wrap your entire response in a single JSON object."
                })
                continue
            
            retry_count = 0  # Reset only after successful parsing
            
            # Validate JSON structure
            step = parsed.get("step", "UNKNOWN")
            content = parsed.get("content", "")
            
            if step == "TOOL":
                tool_name = parsed.get("tool_name")
                if not tool_name:
                    console.print("[bold red]✗ ERROR: tool_name is missing or None![/bold red]")
                    console.print(f"[bold red]Full response:[/bold red] {json.dumps(parsed, indent=2)}")
                    break
            
            # Display Reasoning
            step = parsed.get("step", "UNKNOWN")
            content = parsed.get("content", "")
            
            color = "yellow" if step == "THINK" else "cyan" if step == "TOOL" else "green" if step == "OUTPUT" else "blue"
            console.print(f"\n[bold {color}]{step}:[/bold {color}] {content}")

            # Update history
            messages.append({"role": "assistant", "content": assistant_msg})

            if step == "OUTPUT":
                console.print(Panel(content, title="Final Result", border_style="green"))
                break

            if step == "TOOL":
                tool_name = parsed.get("tool_name")
                tool_args = parsed.get("tool_args", {})
                
                console.print(f"\n[bold cyan]→ TOOL EXECUTION[/bold cyan]")
                console.print(f"  Tool: {tool_name}")
                console.print(f"  Args: {tool_args}")
                
                if tool_name in TOOL_MAP:
                    console.print(f"[bold magenta]Action:[/bold magenta] Calling {tool_name}({tool_args})")
                    
                    # Execute tool
                    result = TOOL_MAP[tool_name](**tool_args)
                    
                    # Truncate result for logs but keep enough for the agent
                    display_result = (result[:100] + '...') if len(str(result)) > 100 else result
                    console.print(f"[bold green]✓ Result:[/bold green] {display_result}")
                    
                    # Add observation to history
                    messages.append({
                        "role": "user", 
                        "content": json.dumps({"step": "OBSERVE", "content": result})
                    })
                else:
                    observation = f"Error: Tool '{tool_name}' not found."
                    console.print(f"[bold red]✗ {observation}[/bold red]")
                    messages.append({
                        "role": "user", 
                        "content": json.dumps({"step": "OBSERVE", "content": observation})
                    })

        except Exception as e:
            console.print(f"[bold red]Critical Error:[/bold red] {str(e)}")
            break

if __name__ == "__main__":
    main()
