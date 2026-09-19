"""Prompt assembly and LLM transport.

Turns a profile into a system prompt, stacks the conversation and any web
context on top, and sends the result to whichever backend is configured -
Ollama, an OpenAI-compatible HTTP endpoint, or a local CLI such as Claude Code
or Codex. Replies come back cleaned of links and of the placeholder text models
sometimes emit in place of real web findings.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from typing import Any
from urllib.parse import urlparse

import requests

from .config import Config
from .storage import read_recent_history

CLI_PROVIDERS = {"claude-code", "codex", "cli"}

PLACEHOLDER_PATTERN = re.compile(r"\[[^\]\n]{3,120}\]")
RAW_URL_PATTERN = re.compile(r"(?i)(?:<\s*)?(?:https?://|www\.)[^\s>]+(?:\s*>)?")
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")

_REPEATED_SPACES = re.compile(r"\s{2,}")
_TRAILING_PUNCTUATION = re.compile(r"[:;,.\-]\s*$")
_NUMBERED_ITEM = re.compile(r"^\d+\.\s+")

_SLIDER_KEYS = (
    "warmth",
    "sass",
    "directness",
    "patience",
    "playfulness",
    "formality",
)

_SUMMARY_MAX_CHARS = 170
_ERROR_SNIPPET_CHARS = 300
_CLI_ERROR_DETAIL_CHARS = 400

_WEB_CONTEXT_INSTRUCTIONS = (
    "Use the following fresh web context when relevant. "
    "Do not fabricate details. Mention source names only and do "
    "not output any links or raw URLs. Never output placeholder text like "
    "[Weather information here] or [Insert source]. "
    "If important details are missing, say what is missing. "
    "Keep the final answer casual and concise by default. "
    "Prefer details from any 'Website excerpt' lines when available."
)


# --------------------------------------------------------------------------
# Value coercion
# --------------------------------------------------------------------------


def _as_clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [text for text in (str(item).strip() for item in value) if text]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _format_list_or_default(items: list[str], fallback: str) -> str:
    return ", ".join(items) if items else fallback


def _as_clean_text(value: Any, fallback: str = "") -> str:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return fallback


def _section(details: dict[str, Any], name: str) -> dict[str, Any]:
    """Read one ``profile_details`` sub-mapping, tolerating junk or absence."""
    value = details.get(name)
    return value if isinstance(value, dict) else {}


def _joined_from(source: dict[str, Any], key: str, fallback: str) -> str:
    return _format_list_or_default(_as_clean_list(source.get(key)), fallback)


# --------------------------------------------------------------------------
# System prompt
# --------------------------------------------------------------------------


def _describe_sliders(sliders: dict[str, Any]) -> str:
    described = [
        f"{key}: {int(value)}/100"
        for key in _SLIDER_KEYS
        for value in (sliders.get(key),)
        if isinstance(value, (int, float))
    ]
    return ", ".join(described) if described else "No slider values provided."


def _describe_rules(custom_rules: dict[str, Any]) -> str:
    rules = _as_clean_list(custom_rules.get("must_follow"))
    if not rules:
        return "- No additional mandatory rules provided."
    return "\n".join(f"- {rule}" for rule in rules)


def build_system_prompt(profile: dict[str, Any]) -> str:
    raw_details = profile.get("profile_details")
    details = raw_details if isinstance(raw_details, dict) else {}

    identity = _section(details, "identity")
    conversation = _section(details, "conversation")
    boundaries = _section(details, "boundaries")
    capabilities = _section(details, "capabilities")
    memory = _section(details, "memory")
    voice = _section(details, "voice")

    slider_summary = _describe_sliders(_section(details, "personality_sliders"))
    additional_rules_text = _describe_rules(_section(details, "custom_rules"))

    goals_text = _joined_from(
        profile, "shared_goals", "have thoughtful, useful conversations"
    )
    memory_text = _joined_from(profile, "memory_notes", "No saved memory notes yet.")
    profile_tags = _joined_from(profile, "tags", "none")

    likes_text = _joined_from(memory, "likes", "No specific likes saved.")
    dislikes_text = _joined_from(memory, "dislikes", "No specific dislikes saved.")
    facts_text = _joined_from(memory, "personal_facts", "No personal facts saved.")

    capabilities_text = _joined_from(
        capabilities, "what_ai_can_do", "chat conversationally"
    )
    forbidden_claims_text = _joined_from(
        capabilities, "forbidden_claims", "abilities outside the current toolset"
    )

    emoji_rule = (
        "Emojis are allowed when they help tone."
        if bool(conversation.get("allow_emojis"))
        else "Do not use emojis, emoticons, or decorative symbols."
    )
    default_reply_length = _as_clean_text(
        conversation.get("default_reply_length"), "short"
    )
    response_pacing = _as_clean_text(conversation.get("response_pacing"), "snappy")
    explanation_style = _as_clean_text(
        conversation.get("explanation_style"), "expand when asked"
    )

    roast_intensity = _as_clean_text(boundaries.get("roast_intensity"), "light")
    roast_rule = (
        f"Roasting is allowed at {roast_intensity} intensity."
        if bool(boundaries.get("allow_roasting", True))
        else "Do not roast or mock the user."
    )

    relationship_style = _as_clean_text(
        identity.get("relationship_style"), "friendly and grounded"
    )
    companion_role = _as_clean_text(
        identity.get("companion_role"), "AI friend and companion"
    )
    voice_delivery_notes = _as_clean_text(
        voice.get("delivery_notes"), "Natural conversational delivery."
    )
    profile_description = _as_clean_text(profile.get("description"), "")

    return f"""
You are {profile['companion_name']}, a {companion_role} for {profile['user_name']}.
Relationship style: {relationship_style}

Profile context:
- Profile name: {profile.get('profile_name', 'Custom Profile')}
- Description: {profile_description or 'No profile description provided.'}
- Tags: {profile_tags}

Core personality:
- {profile['companion_style']}
- Personality sliders: {slider_summary}
- Sound human and natural, not scripted.
- Keep tone consistent with the profile.

Conversation defaults:
- Default reply length: {default_reply_length}
- Response pacing: {response_pacing}
- Explanation style: {explanation_style}
- {emoji_rule}
- {roast_rule}
- Keep answers concise by default, and only go long when asked.
- Use plain language and contractions.
- Do not include raw URLs or hyperlinks in replies unless the user explicitly asks for a link.

Relationship context:
- Your shared goals are: {goals_text}.
- Things to remember about the user: {memory_text}
- User likes: {likes_text}
- User dislikes: {dislikes_text}
- User facts: {facts_text}

Capabilities and limits:
- What you can do in this app: {capabilities_text}
- Never claim abilities beyond available tools.
- Avoid claiming: {forbidden_claims_text}

Voice behavior hints:
- {voice_delivery_notes}

Additional required rules:
{additional_rules_text}

Safety and honesty:
- Never manipulate the user or encourage emotional dependency.
- Never pretend to have a body, real-world presence, or real-life experiences.
- If asked directly, be honest that you are an AI companion.
- Never make up facts when you are unsure; say so plainly.
- Never become hateful, abusive, or degrading.
""".strip()


# --------------------------------------------------------------------------
# Reply post-processing
# --------------------------------------------------------------------------


def _contains_placeholder_markup(text: str) -> bool:
    return bool(PLACEHOLDER_PATTERN.search(text))


def _strip_links_from_reply(text: str) -> str:
    """Drop URLs, keeping markdown link labels, and tidy what that leaves behind."""
    delinked = MARKDOWN_LINK_PATTERN.sub(r"\1", text)
    delinked = RAW_URL_PATTERN.sub("", delinked)

    kept: list[str] = []
    for line in delinked.splitlines():
        cleaned = _REPEATED_SPACES.sub(" ", line).strip()
        cleaned = _TRAILING_PUNCTUATION.sub("", cleaned)
        if cleaned:
            kept.append(cleaned)

    return "\n".join(kept).strip()


# Prefixes recognised inside a web-context block, mapped to the field they fill.
_WEB_FIELD_PREFIXES = (
    ("URL:", "url"),
    ("Snippet:", "snippet"),
    ("Website excerpt:", "excerpt"),
)


def _extract_web_items(web_context: str) -> list[tuple[str, str, str]]:
    """Parse a web-context block into (title, url, best-text) triples."""
    items: list[tuple[str, str, str]] = []
    current = {"title": "", "url": "", "snippet": "", "excerpt": ""}

    def flush() -> None:
        if current["url"] and (current["excerpt"] or current["snippet"]):
            items.append(
                (
                    current["title"] or "Result",
                    current["url"],
                    current["excerpt"] or current["snippet"],
                )
            )

    for raw_line in web_context.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # A numbered line starts a new result and closes the previous one.
        if _NUMBERED_ITEM.match(line):
            flush()
            current = {
                "title": _NUMBERED_ITEM.sub("", line).strip(),
                "url": "",
                "snippet": "",
                "excerpt": "",
            }
            continue

        for prefix, field in _WEB_FIELD_PREFIXES:
            if line.startswith(prefix):
                current[field] = line[len(prefix):].strip()
                break

    flush()
    return items


def _extract_web_query(web_context: str) -> str:
    for raw_line in web_context.splitlines():
        line = raw_line.strip()
        if line.lower().startswith("search query:"):
            return line.split(":", 1)[1].strip()
    return ""


def _shorten(text: str, max_chars: int = _SUMMARY_MAX_CHARS) -> str:
    compact = " ".join(text.strip().split())
    if len(compact) <= max_chars:
        return compact
    clipped = compact[: max_chars - 3].rsplit(" ", 1)[0].strip()
    return (clipped or compact[: max_chars - 3]).rstrip(" ,.;:") + "..."


def _host_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host or "source"


def _unique_hosts(items: list[tuple[str, str, str]]) -> list[str]:
    hosts: list[str] = []
    for _title, url, _snippet in items:
        host = _host_from_url(url)
        if host not in hosts:
            hosts.append(host)
    return hosts


def _build_web_fallback_reply(user_text: str, web_context: str) -> str | None:
    """Compose an answer straight from search results when the model punted."""
    items = _extract_web_items(web_context)
    if not items:
        return None

    search_query = _extract_web_query(web_context)
    first_title, _first_url, first_snippet = items[0]
    summary = _shorten(first_snippet or first_title, max_chars=_SUMMARY_MAX_CHARS)

    lead = "Quick web check"
    if search_query:
        lead += f" for \"{search_query}\""
    reply = f"{lead}: {summary}"

    source_text = ", ".join(_unique_hosts(items)[:2])
    if source_text:
        reply += f" Sources: {source_text}."

    # A weather question with no location in the query is worth a nudge.
    padded_query = f" {search_query.lower()} "
    if "weather" in user_text.lower() and " weather " in padded_query:
        if " in " not in padded_query:
            reply += " Want me to check your exact city/suburb?"
    return reply


def _finalize_reply(reply: str, user_text: str, web_context: str | None) -> str:
    """Swap in a web-derived answer if the model returned placeholder markup."""
    if web_context and _contains_placeholder_markup(reply):
        fallback = _build_web_fallback_reply(user_text, web_context)
        if fallback:
            reply = fallback
    return _strip_links_from_reply(reply)


# --------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------


def _extract_openai_text(message_content: Any) -> str:
    if isinstance(message_content, str):
        return message_content.strip()

    if isinstance(message_content, list):
        parts: list[str] = []
        for item in message_content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text_value = item.get("text")
            if isinstance(text_value, str) and text_value.strip():
                parts.append(text_value.strip())
        return "\n".join(parts).strip()

    return ""


def _sse_payloads(raw_text: str):
    """Yield the decodable JSON payload of each ``data:`` frame."""
    for line in raw_text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            yield json.loads(payload)
        except ValueError:
            continue


def _parse_sse_stream_reply(raw_text: str) -> str:
    """Reconstruct a reply from an OpenAI-style Server-Sent-Events stream.

    Some OpenAI-compatible gateways stream chat-completion chunks even when the
    request explicitly asks for ``stream: false``. The body is then a run of SSE
    frames rather than one JSON object, which the normal parser cannot read, so
    this is the fallback for that shape.
    """
    parts: list[str] = []
    for chunk in _sse_payloads(raw_text):
        choices = chunk.get("choices") if isinstance(chunk, dict) else None
        if not choices:
            continue
        delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
        if not isinstance(delta, dict):
            continue

        content = delta.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.append(_extract_openai_text(content))
    return "".join(parts).strip()


def _body_snippet(response: requests.Response) -> str:
    if not response.text:
        return "(empty body)"
    return response.text.strip()[:_ERROR_SNIPPET_CHARS]


# --------------------------------------------------------------------------
# Ollama
# --------------------------------------------------------------------------


def _request_ollama_reply(
    user_text: str,
    config: Config,
    payload: dict[str, Any],
    web_context: str | None,
) -> str:
    try:
        response = requests.post(
            config.llm_api_url,
            json=payload,
            timeout=config.request_timeout,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "I could not reach Ollama. Install/start Ollama, make sure the server is "
            "running, and confirm the Ollama API URL is correct."
        ) from exc

    try:
        detail = response.json().get("error", "")
    except ValueError:
        detail = response.text.strip()

    if response.status_code >= 400:
        if "not found" in detail.lower():
            raise RuntimeError(
                f"Ollama could not find the model '{config.model}'. "
                f"After installing Ollama, run: ollama pull {config.model}"
            )
        raise RuntimeError(
            f"Ollama returned HTTP {response.status_code}. "
            f"{detail or 'No error details were returned.'}"
        )

    try:
        reply = response.json()["message"]["content"].strip()
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            "Ollama returned an unexpected response format. "
            f"Raw response: {_body_snippet(response)}"
        ) from exc

    return _finalize_reply(reply, user_text, web_context)


# --------------------------------------------------------------------------
# OpenAI-compatible HTTP
# --------------------------------------------------------------------------


def _openai_error_detail(body: Any) -> str:
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return error.get("message") or ""
    return error or ""


def _request_openai_compatible_reply(
    user_text: str,
    config: Config,
    messages: list[dict[str, str]],
    web_context: str | None,
    max_tokens: int | None = None,
) -> str:
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": max_tokens or config.llm_num_predict,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if config.llm_api_key:
        headers["Authorization"] = f"Bearer {config.llm_api_key}"

    try:
        response = requests.post(
            config.llm_api_url,
            json=payload,
            headers=headers,
            timeout=config.request_timeout,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "I could not reach the OpenAI-compatible endpoint. Check the provider, "
            "API URL, and API key."
        ) from exc

    try:
        body = response.json()
        detail = _openai_error_detail(body)
    except ValueError:
        body = None
        detail = response.text.strip()

    if response.status_code >= 400:
        raise RuntimeError(
            f"OpenAI-compatible endpoint returned HTTP {response.status_code}. "
            f"{detail or 'No error details were returned.'}"
        )

    try:
        if body is None:
            body = response.json()
        message = body["choices"][0]["message"]
        reply = _extract_openai_text(message.get("content", ""))
        if not reply:
            raise KeyError("choices[0].message.content")
        return _finalize_reply(reply, user_text, web_context)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        # Some gateways stream chunks despite stream=False above, leaving the
        # body as `data: {...}` SSE frames. Try that shape before giving up.
        sse_reply = _parse_sse_stream_reply(response.text)
        if sse_reply:
            return _finalize_reply(sse_reply, user_text, web_context)
        raise RuntimeError(
            "The OpenAI-compatible endpoint returned an unexpected response "
            f"format. Raw response: {_body_snippet(response)}"
        ) from exc


# --------------------------------------------------------------------------
# Local CLI providers
# --------------------------------------------------------------------------


def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
    """Flatten chat messages into a single prompt for a CLI that takes text."""
    system_parts: list[str] = []
    convo: list[str] = []

    for message in messages:
        content = str(message.get("content", "")).strip()
        if not content:
            continue

        role = message.get("role")
        if role == "system":
            system_parts.append(content)
        elif role == "assistant":
            convo.append(f"Assistant: {content}")
        else:
            convo.append(f"User: {content}")

    prompt = ""
    if system_parts:
        prompt += "\n\n".join(system_parts).strip() + "\n\n"
    return prompt + "\n".join(convo) + "\nAssistant:"


def _resolve_cli(name: str) -> str:
    return shutil.which(name) or name


def _cli_command_parts(config: Config) -> list[str]:
    """Build the argv for the configured CLI (without the prompt)."""
    if config.llm_cli_command:
        return shlex.split(config.llm_cli_command, posix=(os.name != "nt"))

    provider = config.llm_provider
    if provider == "claude-code":
        parts = [
            _resolve_cli(config.claude_cli_path or "claude"),
            "-p",
            "--output-format",
            "text",
        ]
    elif provider == "codex":
        # --skip-git-repo-check: we run in a temp cwd (not a git repo), which
        # codex otherwise refuses. exec reads the prompt from stdin.
        parts = [
            _resolve_cli(config.codex_cli_path or "codex"),
            "exec",
            "--skip-git-repo-check",
        ]
    else:
        raise RuntimeError(
            "No CLI command configured. Set LLM_CLI_COMMAND in your .env."
        )

    if config.cli_model:
        parts += ["--model", config.cli_model]
    return parts


def _run_cli(parts: list[str], stdin_input: str | None, config: Config):
    """Invoke the CLI, routing through a shell on Windows for .cmd/.ps1 shims."""
    options: dict[str, Any] = {
        "input": stdin_input,
        "capture_output": True,
        "text": True,
        # The default Windows locale (cp1252) would mangle emoji and smart
        # quotes, and these CLIs expect UTF-8 on stdin.
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": config.request_timeout,
        "cwd": tempfile.gettempdir(),
    }

    if os.name == "nt":
        # shell=True lets Windows resolve the .cmd/.ps1 wrappers npm installs.
        # Only flags are passed here - the prompt goes via stdin, so there is
        # nothing that could be mis-quoted.
        return subprocess.run(subprocess.list2cmdline(parts), shell=True, **options)
    return subprocess.run(parts, **options)


def _request_cli_reply(
    user_text: str,
    config: Config,
    messages: list[dict[str, str]],
    web_context: str | None,
) -> str:
    prompt = _messages_to_prompt(messages)
    parts = _cli_command_parts(config)
    if not parts:
        raise RuntimeError("The LLM CLI command is empty.")

    # A {prompt} placeholder is substituted in place; otherwise the prompt goes
    # through stdin, which sidesteps argument-length and quoting limits.
    if any("{prompt}" in part for part in parts):
        parts = [part.replace("{prompt}", prompt) for part in parts]
        stdin_input: str | None = None
    else:
        stdin_input = prompt

    try:
        completed = _run_cli(parts, stdin_input, config)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Could not find the '{parts[0]}' CLI. Install it and log in once "
            "(e.g. run `claude` or `codex` in a terminal), or set CLAUDE_CLI_PATH / "
            "CODEX_CLI_PATH / LLM_CLI_COMMAND."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The LLM CLI took too long to respond.") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"The {config.llm_provider} CLI failed (exit {completed.returncode}). "
            f"{detail[:_CLI_ERROR_DETAIL_CHARS] or 'No output. Make sure it is installed and logged in.'}"
        )

    reply = (completed.stdout or "").strip()
    if not reply:
        raise RuntimeError(
            f"The {config.llm_provider} CLI returned no output. "
            "Make sure it is logged in and not waiting for interactive input."
        )

    return _finalize_reply(reply, user_text, web_context)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _assemble_messages(
    user_text: str,
    profile: dict[str, Any],
    config: Config,
    web_context: str | None,
    extra_system: list[str] | None,
    history: list[dict[str, str]] | None,
    speaker_label: str | None,
    system_override: str | None,
) -> list[dict[str, str]]:
    system_prompt = system_override if system_override else build_system_prompt(profile)
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

    messages.extend(
        history if history is not None else read_recent_history(config.history_turns)
    )

    if web_context:
        messages.append({"role": "system", "content": _WEB_CONTEXT_INSTRUCTIONS})
        messages.append({"role": "system", "content": web_context})

    for system_note in extra_system or []:
        note = str(system_note).strip()
        if note:
            messages.append({"role": "system", "content": note})

    messages.append(
        {
            "role": "user",
            "content": f"{speaker_label}: {user_text}" if speaker_label else user_text,
        }
    )
    return messages


def _ollama_payload(
    config: Config, messages: list[dict[str, str]], num_predict: int
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "temperature": config.temperature,
        "num_predict": num_predict,
    }
    # Only pin the context window when configured; otherwise let Ollama pick its
    # default. Capping it lets long-context models load on small GPUs (see
    # OLLAMA_NUM_CTX in config.py).
    if config.llm_num_ctx > 0:
        options["num_ctx"] = config.llm_num_ctx

    return {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "keep_alive": config.llm_keep_alive,
        "options": options,
    }


def request_reply(
    user_text: str,
    profile: dict[str, Any],
    config: Config,
    web_context: str | None = None,
    extra_system: list[str] | None = None,
    history: list[dict[str, str]] | None = None,
    speaker_label: str | None = None,
    max_tokens: int | None = None,
    system_override: str | None = None,
) -> str:
    messages = _assemble_messages(
        user_text,
        profile,
        config,
        web_context,
        extra_system,
        history,
        speaker_label,
        system_override,
    )
    num_predict = max_tokens if max_tokens else config.llm_num_predict

    if config.llm_provider == "ollama":
        return _request_ollama_reply(
            user_text, config, _ollama_payload(config, messages, num_predict), web_context
        )

    if config.llm_provider in CLI_PROVIDERS:
        return _request_cli_reply(user_text, config, messages, web_context)

    return _request_openai_compatible_reply(
        user_text, config, messages, web_context, max_tokens=num_predict
    )
