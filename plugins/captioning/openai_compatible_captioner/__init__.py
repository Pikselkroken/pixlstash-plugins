"""Captioner backed by an OpenAI-compatible vision endpoint.

Holds no model and no VRAM in the PixlStash process.  Every image is
base64-encoded into a ``POST /v1/chat/completions`` on a server you already
run (Ollama, LM Studio, llama.cpp's server, vLLM, anything speaking the same
API) and the reply is the caption.  Nothing is downloaded, ``torch`` is never
imported, and the host gap where nothing calls ``unload()`` costs nothing
here, because there is nothing resident to unload.

Copy the whole ``openai_compatible_captioner`` folder into your user tagger
plugin directory and restart PixlStash Server.  See the README beside this
file.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import urllib.request
from typing import Any

from pixlstash.tagger_plugins.base import TaggerPlugin

logger = logging.getLogger(__name__)

# Ollama's OpenAI-compatible base.  LM Studio is http://localhost:1234/v1.
DEFAULT_ENDPOINT = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen3-vl:8b"
DEFAULT_PROMPT = (
    "Describe this image in one or two sentences. Describe only what is "
    "visible, and do not speculate."
)
DEFAULT_MAX_TOKENS = 256
MAX_TOKENS_MIN, MAX_TOKENS_MAX = 16, 4096
DEFAULT_TIMEOUT = 120
TIMEOUT_MIN, TIMEOUT_MAX = 5, 900
# A caption is a few hundred bytes. This only stops a server that answers
# with an endless body from filling memory.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
# A host that blackholes packets costs a full timeout per image, and the
# description path passes no stop_event, so a dead endpoint would otherwise
# hold the worker for timeout x batch size. Give up after this many requests
# fail in a row and fail the rest of the batch without waiting for them.
MAX_CONSECUTIVE_FAILURES = 5


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Turn every redirect into an error instead of following it.

    ``urllib`` follows redirects without dropping the ``Authorization``
    header, so a redirecting endpoint would hand the user's API key to
    whatever host it names, and could redirect to a scheme the endpoint check
    in :func:`_base_url` exists to refuse.
    """

    def redirect_request(self, *args, **kwargs):
        return None


def _text(parameters: dict[str, Any], key: str, default: str) -> str:
    """Read a string setting, falling back to *default* for junk or blank."""
    value = parameters.get(key, default)
    if not isinstance(value, str):
        return default
    return value.strip() or default


def _integer(
    parameters: dict[str, Any], key: str, default: int, minimum: int, maximum: int
) -> int:
    """Read an integer setting, clamped to the range its schema declares.

    The dialog enforces ``min``/``max``, but saved settings are not
    type-checked and an edited settings file is not checked at all.
    """
    try:
        value = int(parameters.get(key, default))
    except (TypeError, ValueError):
        return default
    return min(max(value, minimum), maximum)


def _base_url(parameters: dict[str, Any]) -> str | None:
    """Return the OpenAI-compatible base URL, or ``None`` if it is unusable.

    ``None`` rather than a fallback on purpose, for every unusable value and
    not only for a bad scheme: urllib opens file:// and ftp:// as happily as
    http://, and quietly substituting some other server would send the images,
    and the API key, somewhere the user did not type. An absent setting still
    gets the default, since that is what a default is for.
    """
    endpoint = parameters.get("endpoint", DEFAULT_ENDPOINT)
    if not isinstance(endpoint, str):
        return None
    endpoint = endpoint.strip().rstrip("/")
    if not endpoint.lower().startswith(("http://", "https://")):
        return None
    if "?" in endpoint or "#" in endpoint:
        # This is a base URL that gets a path appended, so a query or a
        # fragment would end up in the middle of the request URL.
        return None
    if not endpoint.lower().endswith("/v1"):
        # The address people know is the server's, not the API version's.
        endpoint += "/v1"
    return endpoint


def _request(url: str, payload: dict | None, api_key: str, timeout: int) -> Any:
    """POST *payload* as JSON, or GET when it is ``None``, and parse the reply.

    *timeout* bounds each socket operation rather than the call as a whole, so
    a server that dribbles its answer out slowly enough can still outlast it,
    and name resolution happens before any of it and is bounded by the
    system resolver alone. That is the ceiling without a thread to cancel
    from, and this path has no ``stop_event`` to cancel with; the read is
    capped instead, so a misbehaving server costs time and not memory.
    """
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers)
    # Built per call, and with an empty ProxyHandler. The default one reads
    # http_proxy/ALL_PROXY from the environment, which would route the request
    # (and with it the API key and the image) through a host the user never
    # named in the endpoint field.
    opener = urllib.request.build_opener(_NoRedirects, urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError(f"reply larger than {MAX_RESPONSE_BYTES} bytes")
    return json.loads(body.decode("utf-8"))


def _data_uri(path: str) -> str | None:
    """Return *path* as a base64 data URI, or ``None`` if it is not an image.

    The type comes from the extension, since ``image_paths`` may contain video
    and a video cannot go in a chat message. A file with no extension, or one
    the host's mime table does not know, is treated as not an image.
    """
    mime, _ = mimetypes.guess_type(path)
    if mime is None or not mime.startswith("image/"):
        return None
    with open(path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _payload(model: str, prompt: str, data_uri: str, max_tokens: int) -> dict[str, Any]:
    """Build one chat-completions request: the prompt and one image."""
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
        "max_tokens": max_tokens,
        "stream": False,
    }


def _caption_text(body: Any) -> str | None:
    """Pull the caption out of a chat-completions reply.

    Indexed rather than ``.get()``-ed on purpose: a reply that is not the
    shape the API documents raises, and the caller turns that into one failed
    image rather than a caption reading "None".
    """
    content = body["choices"][0]["message"]["content"]
    if isinstance(content, list):
        # Some servers answer with the list-of-parts shape requests use. Only
        # the string parts: a part carrying anything else is not text.
        content = "".join(
            part["text"]
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    if not isinstance(content, str) or not content.strip():
        # Empty is a failure, not a caption: a thinking model that spends the
        # whole token budget on its reasoning lands here.
        return None
    return content.strip()


class OpenAICompatibleCaptioner(TaggerPlugin):
    """Captions images with a vision model served over the OpenAI chat API."""

    name = "openai_compatible_captioner"
    display_name = "OpenAI-Compatible Vision API"
    description = (
        "Captions images with a vision model on an OpenAI-compatible server "
        "(Ollama, LM Studio, ...). Loads nothing locally."
    )
    # The header a tool reads to describe this plugin. Keep the values literal:
    # they are meant to be readable without importing the plugin.
    author = "PixlStash plugins <https://github.com/Pikselkroken/PixlStash-plugins>"
    license = "MIT"
    # The model is whichever one the user's server is serving, so this names
    # the default. There is no revision to pin from here: an Ollama tag is
    # resolved on the server, and re-pulling it can change the weights.
    models = [
        {
            "name": "qwen3-vl:8b (default; any vision model on the endpoint)",
            "license": "Apache-2.0 (Qwen/Qwen3-VL-8B-Instruct)",
        },
    ]

    supports_tags = False
    supports_descriptions = True
    requires_download = False

    def __init__(self) -> None:
        self._ready = False

    # ------------------------------------------------------------------
    # Schema: this JSON *is* the settings UI
    # ------------------------------------------------------------------

    def parameter_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "endpoint",
                "label": "Endpoint",
                "type": "string",
                "default": DEFAULT_ENDPOINT,
                "description": (
                    "Base URL of the OpenAI-compatible server. Ollama is "
                    "http://localhost:11434/v1, LM Studio is "
                    "http://localhost:1234/v1. /v1 is appended if you leave "
                    "it off, and anything that is not an http(s) URL captions "
                    "nothing rather than guessing."
                ),
            },
            {
                "name": "model",
                "label": "Model",
                "type": "string",
                "default": DEFAULT_MODEL,
                "description": (
                    "Model id as the server reports it, and it must be a "
                    "vision model: qwen3-vl:8b, qwen2.5vl:7b, llava:7b, "
                    "minicpm-v. Pull it on the server first."
                ),
            },
            {
                "name": "prompt",
                "label": "Prompt",
                "type": "textarea",
                "default": DEFAULT_PROMPT,
                "description": "Instruction sent with every image.",
            },
            {
                "name": "max_tokens",
                "label": "Max tokens",
                "type": "integer",
                "default": DEFAULT_MAX_TOKENS,
                "min": MAX_TOKENS_MIN,
                "max": MAX_TOKENS_MAX,
                "step": 16,
                "description": (
                    "Upper bound on caption length. A thinking model spends "
                    "this budget on its reasoning first and returns nothing "
                    "if it runs out, so do not set it low."
                ),
            },
            {
                "name": "timeout_seconds",
                "label": "Timeout (seconds)",
                "type": "integer",
                "default": DEFAULT_TIMEOUT,
                "min": TIMEOUT_MIN,
                "max": TIMEOUT_MAX,
                "step": 5,
                "description": (
                    "Per-image request timeout. An image that takes longer is "
                    "left uncaptioned; the batch continues."
                ),
            },
            {
                "name": "api_key",
                "label": "API key",
                "type": "string",
                "default": "",
                "description": (
                    "Sent as 'Authorization: Bearer ...'. Leave empty for a "
                    "local Ollama or LM Studio, which need none. Stored in "
                    "plain text in your tagger settings, so use a key you can "
                    "revoke."
                ),
            },
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def needs_download(self, parameters: dict[str, Any] | None = None) -> bool:
        """Always False: the model lives on the server, not here.

        This was an obvious place to hang "is the endpoint up and is the model
        pulled?", but the host cannot use the answer. Its only caller is the
        download route (``routes/taggers.py``), which calls this with no
        parameters, so the check would never see the user's endpoint or model,
        and a True would start a background ``download()`` that does nothing
        and report ``{"status": "started"}`` for it.

        A failed request says why in the server log instead.
        """
        return False

    def init(self, parameters: dict[str, Any]) -> None:
        """No model to load. The settings are read per request instead."""
        self._ready = True

    def unload(self) -> None:
        self._ready = False

    def is_loaded(self) -> bool:
        """Whether the plugin is ready to send requests.

        Not whether the endpoint is up: the settings table polls this, and
        ``plugin_schema()`` calls it on the request thread, so probing the
        network here would block the settings screen on every poll.
        ``needs_download()`` is where the endpoint gets checked.
        """
        return self._ready

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def generate_descriptions(
        self,
        image_paths: list[str],
        parameters: dict[str, Any],
        stop_event=None,
    ) -> dict[str, str | None]:
        """Return an entry per path. ``None`` marks a per-image failure.

        Only a ``stop_event`` leaves a path out, and today nothing passes one.
        """
        # Saved settings are validated by name but not by type, so read them
        # defensively. Note `.get(key, default)` rather than `.get(key) or
        # default`, which turns a deliberate 0 into the default.
        base = _base_url(parameters)
        if base is None:
            logger.warning(
                "%s: the endpoint setting is not an http(s) URL; captioning "
                "nothing rather than sending images elsewhere",
                self.name,
            )
            return dict.fromkeys(image_paths)
        url = base + "/chat/completions"
        model = _text(parameters, "model", DEFAULT_MODEL)
        prompt = _text(parameters, "prompt", DEFAULT_PROMPT)
        max_tokens = _integer(
            parameters, "max_tokens", DEFAULT_MAX_TOKENS, MAX_TOKENS_MIN, MAX_TOKENS_MAX
        )
        timeout = _integer(
            parameters, "timeout_seconds", DEFAULT_TIMEOUT, TIMEOUT_MIN, TIMEOUT_MAX
        )
        api_key = _text(parameters, "api_key", "")

        results: dict[str, str | None] = {}
        failures = 0
        for index, path in enumerate(image_paths):
            # stop_event is always None on the description path today; guard
            # the access rather than assume it stays that way.
            if stop_event is not None and stop_event.is_set():
                break
            if failures >= MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    "%s: %s failed %d times in a row; failing the remaining "
                    "%d images without waiting for it",
                    self.name,
                    url,
                    failures,
                    len(image_paths) - index,
                )
                results.update(dict.fromkeys(image_paths[index:]))
                break
            # Reading the file is a separate step from sending it, and only
            # on purpose: an unreadable picture says nothing about the server,
            # so it must not count towards the breaker. Five files in a row
            # that PixlStash cannot open would otherwise discard the batch.
            try:
                data_uri = _data_uri(path)
            except Exception as exc:
                logger.warning("%s: %s could not be read: %s", self.name, path, exc)
                results[path] = None
                continue
            if data_uri is None:
                logger.warning("%s: %s is not an image this can send", self.name, path)
                results[path] = None
                continue
            try:
                results[path] = _caption_text(
                    _request(
                        url,
                        _payload(model, prompt, data_uri, max_tokens),
                        api_key,
                        timeout,
                    )
                )
                failures = 0
            except Exception as exc:
                # A refused connection, a timeout, an HTTP error, a redirect,
                # a body that is not the shape the API documents: each costs
                # this image only, since raising would lose the whole batch.
                # Logged because otherwise every one of them looks the same
                # from the UI: a picture with no description.
                logger.warning("%s: %s was not captioned: %s", self.name, path, exc)
                results[path] = None
                failures += 1
        return results


if __name__ == "__main__":
    # Offline check of the settings handling and the reply parsing, the parts
    # with branches in them. Needs pixlstash installed, like the plugin does:
    # python plugins/captioning/openai_compatible_captioner/__init__.py
    assert _base_url({}) == DEFAULT_ENDPOINT
    assert _base_url({"endpoint": "http://10.0.0.1:1234/"}) == "http://10.0.0.1:1234/v1"
    assert (
        _base_url({"endpoint": "http://10.0.0.1:1234/v1"}) == "http://10.0.0.1:1234/v1"
    )
    assert _base_url({"endpoint": "HTTPS://10.0.0.1"}) == "HTTPS://10.0.0.1/v1"
    assert _base_url({"endpoint": "file:///etc/passwd"}) is None
    assert _base_url({"endpoint": "https//10.0.0.1/v1"}) is None
    assert _base_url({"endpoint": 42}) is None
    assert _base_url({"endpoint": "  "}) is None
    assert _base_url({"endpoint": "http://10.0.0.1/v1?api-version=1"}) is None
    assert _text({"model": "   "}, "model", DEFAULT_MODEL) == DEFAULT_MODEL
    assert _text({"model": " qwen3-vl:8b "}, "model", DEFAULT_MODEL) == "qwen3-vl:8b"
    assert _integer({"max_tokens": "junk"}, "max_tokens", 256, 16, 4096) == 256
    assert _integer({"max_tokens": 0}, "max_tokens", 256, 16, 4096) == 16
    assert _integer({"max_tokens": 10**9}, "max_tokens", 256, 16, 4096) == 4096
    assert _integer({"max_tokens": 32}, "max_tokens", 256, 16, 4096) == 32
    assert _data_uri("/home/me/clip.mp4") is None
    assert _data_uri("/home/me/no_extension") is None
    assert (
        _caption_text({"choices": [{"message": {"content": " A cat. "}}]}) == "A cat."
    )
    assert _caption_text({"choices": [{"message": {"content": "  "}}]}) is None
    parts = [{"type": "text", "text": "A cat."}]
    assert _caption_text({"choices": [{"message": {"content": parts}}]}) == "A cat."
    mixed = [{"type": "text", "text": "A cat."}, {"type": "image_url", "image_url": {}}]
    assert _caption_text({"choices": [{"message": {"content": mixed}}]}) == "A cat."
    try:
        _caption_text({"error": {"message": "model not found"}})
    except (KeyError, IndexError, TypeError):
        pass  # what the batch loop turns into one failed image
    else:
        raise AssertionError("a malformed reply must raise, not caption")

    # The batch loop, with the network and the disk stubbed out. Both stubs
    # replace a module global, which is what the loop calls.
    plugin = OpenAICompatibleCaptioner()
    plugin.init({})
    paths = [f"/home/me/{index}.png" for index in range(8)]
    sent = []

    def _refused(url, payload, api_key, timeout):
        sent.append(url)
        raise OSError("connection refused")

    def _one_pixel(path):
        return "data:image/png;base64,AA=="

    _request = _refused
    _data_uri = _one_pixel
    result = plugin.generate_descriptions(paths, {})
    assert set(result) == set(paths), "every path must come back, failed or not"
    assert set(result.values()) == {None}
    assert len(sent) == MAX_CONSECUTIVE_FAILURES, "the breaker must stop the batch"

    def _unreadable_but_the_last_two(path):
        if path.endswith(("6.png", "7.png")):
            return "data:image/png;base64,AA=="
        raise PermissionError("permission denied")

    _data_uri = _unreadable_but_the_last_two
    sent.clear()
    result = plugin.generate_descriptions(paths, {})
    assert set(result) == set(paths)
    assert len(sent) == 2, "files that cannot be read must not arm the breaker"

    assert plugin.generate_descriptions(paths, {"endpoint": "nope"}) == dict.fromkeys(
        paths
    ), "an unusable endpoint fails every image and sends nothing"
    print("ok")
