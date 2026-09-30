"""Free-LLM adapter. Providers (all have a free option):

  ollama : local, fully offline / air-gapped   (ollama pull qwen2.5:7b)
  groq   : free API tier, OpenAI-compatible    (GROQ_API_KEY)
  gemini : free API tier, Google AI Studio     (GEMINI_API_KEY)
  none   : no LLM - every feature falls back to deterministic logic

Select with COALMIND_LLM=auto|ollama|groq|gemini|none (default auto).
Override model with COALMIND_MODEL. Responses are cached on disk, so a demo
replays without network (blueprint: "cache extraction results").
"""
import hashlib, json, os, re, sys, time
import requests
from dotenv import load_dotenv

load_dotenv()

from .config import CACHE

DEFAULT_MODELS = {
    "ollama": "qwen2.5:7b",              # use llama3.2:3b on low-RAM laptops
    "groq": "llama-3.3-70b-versatile",
    "gemini": "gemini-3.5-flash-lite",
}
last_error = None
_provider = None


def provider():
    global _provider
    if _provider:
        return _provider
    p = os.getenv("COALMIND_LLM", "auto").lower()
    if p == "auto":
        if os.getenv("GROQ_API_KEY"):
            p = "groq"
        elif os.getenv("GEMINI_API_KEY"):
            p = "gemini"
        else:
            try:
                requests.get(os.getenv("OLLAMA_URL", "http://localhost:11434") + "/api/tags", timeout=1).raise_for_status()
                p = "ollama"
            except Exception:
                p = "none"
    _provider = p
    return p


def model():
    return os.getenv("COALMIND_MODEL") or DEFAULT_MODELS.get(provider(), "")


def available():
    return provider() != "none"


def status():
    return f"{provider()} ({model()})" if available() else "none (deterministic fallback mode)"


def extract_json(text):
    """Tolerant JSON extraction from an LLM reply."""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _call(system, user, json_mode, max_tokens):
    p, m = provider(), model()
    if p == "ollama":
        body = {"model": m, "stream": False, "options": {"temperature": 0, "num_predict": max_tokens},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode:
            body["format"] = "json"
        r = requests.post(os.getenv("OLLAMA_URL", "http://localhost:11434") + "/api/chat", json=body, timeout=300)
        r.raise_for_status()
        return r.json()["message"]["content"]
    if p == "groq":
        body = {"model": m, "temperature": 0, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = requests.post("https://api.groq.com/openai/v1/chat/completions", json=body, timeout=120,
                          headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    if p == "gemini":
        gen = {"temperature": 0, "maxOutputTokens": max_tokens}
        if json_mode:
            gen["responseMimeType"] = "application/json"
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": gen}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
        r = requests.post(url, json=body, timeout=120, params={"key": os.environ["GEMINI_API_KEY"]})
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return None


def chat(system, user, json_mode=False, max_tokens=1200):
    """Returns the model text, or None if no LLM is available / the call failed."""
    global last_error
    if not available():
        return None
    key = hashlib.sha256(json.dumps([provider(), model(), system, user, json_mode]).encode()).hexdigest()
    f = CACHE / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))["text"]
    for attempt in range(3):
        try:
            text = _call(system, user, json_mode, max_tokens)
            if text:
                f.write_text(json.dumps({"text": text}), encoding="utf-8")
            return text
        except requests.HTTPError as e:            # free tiers rate-limit: back off and retry
            last_error = str(e)
            if e.response is not None and e.response.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            break
        except Exception as e:
            last_error = str(e)
            break
    print(f"[llm] call failed, using fallback: {last_error}", file=sys.stderr)
    return None
