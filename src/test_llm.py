"""Verify that WSL can reach an LM Studio OpenAI-compatible API server."""

import os
import subprocess

from openai import APIConnectionError, APIError, OpenAI


PROMPT = PROMPT = "Write an IEC 61131-3 ST logic where OutputC is TRUE if InputA and InputB are TRUE. Output ONLY raw ST code. Do not use markdown block (```). No explanations, no comments, no greetings."


def get_wsl_host_ip() -> str:
    """Return the WSL default gateway IP, or localhost as a fallback."""
    try:
        result = subprocess.run(
            ["sh", "-c", "ip route show default | awk '{print $3}'"],
            check=True,
            capture_output=True,
            text=True,
        )
        host_ip = result.stdout.strip()
        if host_ip:
            return host_ip
    except (OSError, subprocess.SubprocessError):
        return "localhost"

    return "localhost"


BASE_URL = os.getenv("LM_STUDIO_BASE_URL", f"http://{get_wsl_host_ip()}:1234/v1")


def main() -> None:
    print(f"Using LM Studio base URL: {BASE_URL}")
    client = OpenAI(base_url=BASE_URL, api_key="lm-studio")

    try:
        models = client.models.list()
        if not models.data:
            print("LM Studio is reachable, but no model is loaded.")
            print("Load a chat-capable model in LM Studio and run this script again.")
            return

        model_id = models.data[0].id
        print(f"Using LM Studio model: {model_id}")

        response = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": PROMPT}],
        )

        message = response.choices[0].message.content
        print("\nModel response:")
        print(message or "(The model returned an empty response.)")
    except APIConnectionError as exc:
        print(f"Could not connect to LM Studio at {BASE_URL}.")
        print("Check that LM Studio is running and its local server is listening on port 1234.")
        print("Check that LM Studio allows connections from the WSL network.")
        print(f"Connection error: {exc}")
    except APIError as exc:
        print(f"LM Studio returned an API error: {exc}")


if __name__ == "__main__":
    main()
