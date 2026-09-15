"""Bounded ReAct CLI. Importing this module never loads credentials or starts a client."""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from prompt_config import SYSTEM_PROMPT
from tools import Dispatcher
from webcloner.audit import sanitized_arguments
from webcloner.redaction import redact

ROOT = Path(__file__).resolve().parent
TOOL_STEPS = {
    "FETCH_URL": "fetch_url",
    "DOWNLOAD_ASSET": "download_asset",
    "CLONE_PAGE": "clone_page",
    "WRITE_FILE": "write_file",
    "REPLACE_TEXT": "replace_text",
    "READ_FILE": "read_file",
    "LIST_FILES": "list_files",
    "EXECUTE_COMMAND": "execute_command",
}
SIMPLE_CLONE = re.compile(r"^\s*clone\s+(https://[^\s<>\"']+?)\s*[.!]?\s*$", re.I)


def simple_clone_target(prompt):
    """Return a URL only for an unambiguous one-URL clone command."""
    if not isinstance(prompt, str):
        return None
    match = SIMPLE_CLONE.fullmatch(prompt)
    return match.group(1) if match else None


def run_static_clone(dispatcher, url):
    result = dispatcher.dispatch("clone_page", {"url": url})
    print(json.dumps({"decision": result["decision"], "ok": result["ok"], "error": result.get("error")}, ensure_ascii=True))
    if not result["ok"]:
        return False
    print(json.dumps({"step": "OUTPUT", "content": "Static clone completed with the source page's localized HTML and CSS.",
                      "result": result.get("output", {})}, ensure_ascii=True))
    return True


def extract_first_json(text):
    # Strict parsing avoids ambiguous multiple actions or prose-wrapped JSON.
    if not isinstance(text, str) or len(text.encode()) > 1_100_000:
        raise ValueError("Model response missing or too large")
    value = json.loads(text)
    if type(value) is not dict or type(value.get("step")) is not str:
        raise ValueError("Invalid response envelope")
    step = value["step"].upper()
    if step in TOOL_STEPS:
        # Some instruction-following models emit {step: LIST_FILES, directory: .}.
        # Normalize only known tools; the dispatcher still performs exact schema
        # validation and policy evaluation before any side effect.
        if "tool_args" in value:
            if set(value) - {"step", "tool_args", "content"}:
                raise ValueError("Invalid shorthand tool fields")
            arguments = value["tool_args"]
        else:
            arguments = {key: item for key, item in value.items() if key not in ("step", "content")}
        return {"step": "TOOL", "tool_name": TOOL_STEPS[step], "tool_args": arguments,
                "content": value.get("content", "")}
    value["step"] = step
    if step not in ("THINK", "TOOL", "OUTPUT"):
        raise ValueError("Invalid response envelope")
    allowed = {"step", "tool_name", "tool_args", "content"} if value["step"] == "TOOL" else {"step", "content"}
    if set(value) - allowed or ("content" in value and type(value["content"]) is not str):
        raise ValueError("Invalid response fields")
    return value


def terminal_approval(request, decision):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    print(json.dumps(redact({"approval_request": request.action, "arguments": sanitized_arguments(request.arguments),
                             "sha256": hashlib.sha256(request.arguments_json.encode()).hexdigest(),
                             "decision": decision.to_dict()}), indent=2, ensure_ascii=True))
    return input(f"Approve this action once? Type {request.request_id}: ") == request.request_id


def run_loop(dispatcher, responses, user_input, max_steps=40):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_input}]
    invalid_responses = 0
    read_files = set()
    think_steps = 0
    for _ in range(max_steps):
        try:
            raw = responses(messages)
            parsed = extract_first_json(raw)
        except StopIteration:
            print(json.dumps({"error": "Recorded responses exhausted"}))
            return False
        except ValueError as exc:
            invalid_responses += 1
            if invalid_responses >= 3:
                preview = redact(raw[:160]) if isinstance(raw, str) and raw else "<empty>"
                print(json.dumps({"error": "Model returned invalid JSON after 3 attempts", "detail": str(exc), "response_preview": preview}))
                return False
            if isinstance(raw, str) and raw:
                messages.append({"role": "assistant", "content": redact(raw[:2000])})
            messages.append({"role": "user", "content": "Your previous response was invalid. Return one JSON object only, matching the required step schema."})
            continue
        invalid_responses = 0
        messages.append({"role": "assistant", "content": redact(raw)})
        if parsed["step"] == "TOOL":
            result = dispatcher.dispatch(parsed.get("tool_name"), parsed.get("tool_args"))
            if parsed.get("tool_name") == "read_file" and result["ok"]:
                filename = parsed["tool_args"]["filename"]
                if filename in read_files:
                    result["output"] = {"filename": filename, "notice": "This file preview was already provided. Use replace_text or write_file now; do not read it again."}
                read_files.add(filename)
            print(json.dumps({"decision": result["decision"], "ok": result["ok"], "error": result.get("error")}, ensure_ascii=True))
            messages.append({"role": "user", "content": json.dumps({"step": "OBSERVE", "content": result})})
            think_steps = 0
        else:
            print(json.dumps(redact(parsed), ensure_ascii=True))
            if parsed["step"] == "OUTPUT":
                return True
            think_steps += 1
            if think_steps >= 2:
                instruction = "Do not THINK again. Select the next TOOL now, preferably replace_text for a focused edit, or OUTPUT only if the requested work is complete."
            else:
                instruction = "Continue now. Use the canonical TOOL envelope for an action, or OUTPUT when finished. For a focused edit after reading a file, use replace_text rather than reading it again."
            messages.append({"role": "user", "content": instruction})
    print('{"error":"Agent step limit reached"}')
    return False


def main():
    parser = argparse.ArgumentParser(description="Website cloning with a deterministic tool policy")
    parser.add_argument("prompt", nargs="?", default="Clone https://example.com/")
    parser.add_argument("--workspace", type=Path, default=ROOT / "output" / "site")
    parser.add_argument("--policy", type=Path, default=ROOT / "policies/default.json")
    parser.add_argument("--audit", type=Path, default=ROOT / ".webcloner/events.jsonl")
    parser.add_argument("--recording", type=Path, help="Replay operator-supplied JSON responses offline")
    parser.add_argument("--max-steps", type=int, default=40)
    args = parser.parse_args()
    dispatcher = None
    try:
        if not 1 <= args.max_steps <= 100:
            raise ValueError("max-steps must be between 1 and 100")
        dispatcher = Dispatcher(args.workspace, args.policy, args.audit, approval_ui=terminal_approval)
        if args.recording:
            recorded = iter(json.loads(args.recording.read_text()))
            responses = lambda messages: json.dumps(next(recorded))
        else:
            target = simple_clone_target(args.prompt)
            if target:
                return 0 if run_static_clone(dispatcher, target) else 1
            # Existing provider preserved; read credentials only for an explicit live run.
            from openai import OpenAI
            key = os.environ.get("HUGGINGFACE_API_KEY")
            if not key:
                raise ValueError(
                    "Set HUGGINGFACE_API_KEY for a complex model-backed prompt. "
                    "An exact 'Clone https://…' command uses the key-free static snapshot path"
                )
            client = OpenAI(api_key=key, base_url="https://router.huggingface.co/v1")
            max_tokens = int(os.environ.get("WEBCLONER_MAX_TOKENS", "8000"))
            if not 512 <= max_tokens <= 16_000:
                raise ValueError("WEBCLONER_MAX_TOKENS must be between 512 and 16000")

            def responses(messages):
                response = client.chat.completions.create(
                    model=os.environ.get("WEBCLONER_MODEL", "MiniMaxAI/MiniMax-M2.7"),
                    messages=messages, temperature=0.2, max_tokens=max_tokens, timeout=120,
                    response_format={"type": "json_object"},
                )
                return response.choices[0].message.content

        return 0 if run_loop(dispatcher, responses, args.prompt, args.max_steps) else 1
    except Exception as exc:
        print(json.dumps({"error": redact(str(exc))}, ensure_ascii=True), file=sys.stderr)
        return 1
    finally:
        if dispatcher:
            dispatcher.close()


if __name__ == "__main__":
    raise SystemExit(main())
