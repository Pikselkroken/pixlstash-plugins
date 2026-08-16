"""Moondream2 captioner plugin for PixlStash.

Wraps `vikhyatk/moondream2 <https://huggingface.co/vikhyatk/moondream2>`_, a
~1.9B vision language model, and offers its two text skills: ``caption()``
for a couple of natural sentences about the frame, and ``query()`` for a
question you type once and get answered for every picture in the batch.

Two things worth knowing before you install it:

1. **It runs the model's own Python.** Moondream ships as remote code:
   transformers downloads the ``.py`` files from the model repository and
   executes them in this process, and installing this plugin consents to that
   on your behalf. That is largely moot here, since PixlStash already runs
   plugin code unsandboxed in the same process, but you are trusting one more
   repository than you were, which is why the revision below is pinned rather
   than tracking ``main``.
2. **It downloads about 3.9 GB on first use.** The plugin sets
   ``requires_download``, so **Settings -> Auto-tagging** offers a download
   button that fetches the weights ahead of the first batch; without it the
   first caption blocks on the download instead. The ``.gguf`` copies in the
   repository are skipped, since the ``transformers`` path reads
   ``model.safetensors``.

Nothing calls ``unload()`` on a third-party plugin, so once a batch has run,
those 3.9 GB stay resident for the life of the server process. That is the whole
reason this wraps a small model.

Copy the whole ``moondream2_captioner`` folder into your user tagger plugin
directory and restart PixlStash Server. See the repository README.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import torch
from huggingface_hub import (
    hf_hub_download,
    scan_cache_dir,
    snapshot_download,
    try_to_load_from_cache,
)
from PIL import Image
from pixlstash.tagger_plugins.base import TaggerPlugin
from safetensors.torch import load_file
from transformers import AutoConfig
from transformers.dynamic_module_utils import get_class_from_dynamic_module

MODEL_REPO = "vikhyatk/moondream2"

# Pinned deliberately. Moondream re-points `main` at each release, and an
# unpinned ref is a silent supply-chain change as well as a silent change of
# caption style. 2025-06-21 is the current release.
MODEL_REVISION = "2025-06-21"

# The repository also ships llama.cpp builds of the same weights, another
# 3.75 GB the transformers path never opens.
IGNORE_PATTERNS = ["*.gguf"]

# The model ships one unsharded checkpoint and one entry class. Both are safe
# to name here because the revision above is pinned.
WEIGHTS_FILE = "model.safetensors"
MODEL_CLASS_REF = "hf_moondream.HfMoondream"

# The artifact name is a URL path segment in
# `DELETE /taggers/{name}/artifacts/{id}`, so it must not contain the slash in
# the repo id.
ARTIFACT_NAME = "moondream2"

DEFAULT_MODE = "caption"
DEFAULT_LENGTH = "normal"
DEFAULT_QUESTION = "Describe what is happening in this image."
DEFAULT_MAX_TOKENS = 256

# `caption()` raises ValueError for a length the checkpoint has no prompt
# template for. All three are present in this revision (checked against
# `config.tokenizer.templates["caption"]`), though the model card documents
# only the first two.
LENGTHS = ("short", "normal", "long")


def _cached_weights() -> str | None:
    """Return the path to the cached checkpoint, or ``None`` if it is absent.

    This asks for the weights file rather than for the revision, because
    `snapshot_download` writes `refs/<revision>` before it fetches anything: a
    download killed part-way leaves the ref behind, and a plugin that took the
    ref as proof would hide its own download button and report a half-fetched
    4 GB as a finished artifact.

    It is also on a hot path. `plugin_schema()` calls
    `list_downloaded_artifacts()`, the registry exercises that at load and the
    settings table polls it, so this has to be a lookup rather than a walk of a
    HuggingFace cache holding every other model on the machine. Best-effort,
    too: a raise here takes the settings screen down with it.
    """
    try:
        path = try_to_load_from_cache(MODEL_REPO, WEIGHTS_FILE, revision=MODEL_REVISION)
    except Exception:
        return None
    # Returns the sentinel object `_CACHED_NO_EXIST` for a file known to be
    # absent upstream, so check the type rather than truthiness.
    return path if isinstance(path, str) else None


class Moondream2Captioner(TaggerPlugin):
    """Describes an image with Moondream2, or answers a question about it."""

    name = "moondream2"
    display_name = "Moondream2"
    description = "Natural-language captions and visual Q&A from Moondream2."

    supports_tags = False
    supports_descriptions = True
    requires_download = True

    def __init__(self) -> None:
        self._model = None
        self._device = "cpu"
        # init() runs on the batch thread, delete_artifact() on a request
        # thread. Without this, two callers can both find no model and both
        # load 4 GB of it.
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Schema: this JSON *is* the settings UI
    # ------------------------------------------------------------------

    def parameter_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "mode",
                "label": "Mode",
                "type": "select",
                "default": DEFAULT_MODE,
                "options": [
                    {"value": "caption", "label": "Caption the image"},
                    {"value": "query", "label": "Answer a question"},
                ],
                "description": (
                    "Caption describes the picture. Answer a question runs the "
                    "question below against every picture instead."
                ),
            },
            {
                "name": "length",
                "label": "Caption length",
                "type": "select",
                "default": DEFAULT_LENGTH,
                "options": [
                    {"value": "short", "label": "Short (one sentence)"},
                    {"value": "normal", "label": "Normal (a few sentences)"},
                    {"value": "long", "label": "Long (a paragraph or two)"},
                ],
                "description": (
                    "Ignored in question mode. Long needs a higher token "
                    "budget than the default to finish."
                ),
            },
            {
                "name": "question",
                "label": "Question",
                "type": "textarea",
                "default": DEFAULT_QUESTION,
                "description": (
                    "Asked of every picture in question mode, for example "
                    '"What is the subject wearing?". Ignored in caption mode.'
                ),
            },
            {
                "name": "max_tokens",
                "label": "Max tokens",
                "type": "integer",
                "default": DEFAULT_MAX_TOKENS,
                "min": 16,
                "max": 1024,
                "step": 16,
                "description": (
                    "Upper bound on the generated text. A normal caption rarely "
                    "needs more than 256."
                ),
            },
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self, device: str) -> None:
        """Receive the inference device. The only way to learn it."""
        self._device = device

    def init(self, parameters: dict[str, Any]) -> None:
        """Load Moondream2 onto ``self._device``. Called before every batch.

        Built and then filled from the checkpoint by hand, rather than through
        ``AutoModelForCausalLM.from_pretrained``, because that path is broken
        for this model on the transformers PixlStash ships. Two reasons, and
        the second one is the dangerous one:

        1. transformers 5 reads ``model.all_tied_weights_keys``, which is set
           in ``PreTrainedModel.post_init()``. Moondream's ``HfMoondream``
           never calls it, so the load raises ``AttributeError``.
        2. transformers 5 always constructs the model on the meta device and
           then materialises it from the checkpoint. Moondream builds its
           causal mask in ``__init__`` as a **non-persistent** buffer, so it is
           not in the checkpoint: it comes back as uninitialised memory, and
           the model then captions every picture with fluent nonsense. Nothing
           raises, and both the weights and the tensor shapes check out
           afterwards, so this is a silent wrong answer rather than a failure.

        Building it outside that machinery, on a real device rather than on
        meta, sidesteps both. What it gives up is the checkpoint resolution
        ``from_pretrained`` does, which is why the weights file name and the
        entry class are constants up top: safe to hardcode only because the
        revision is pinned, and to be rechecked if that pin ever moves.
        """
        with self._lock:
            if self._model is not None:
                return
            # Loaded here rather than at module level: the registry constructs
            # the plugin at start-up, and a 4 GB model has no business loading
            # before somebody asks for a caption.
            model_class = get_class_from_dynamic_module(
                MODEL_CLASS_REF, MODEL_REPO, revision=MODEL_REVISION
            )
            config = AutoConfig.from_pretrained(
                MODEL_REPO, revision=MODEL_REVISION, trust_remote_code=True
            )
            model = model_class(config)
            # strict, so a checkpoint that stopped matching this class is a
            # loud failure at load rather than a quiet one at caption time.
            model.load_state_dict(
                load_file(
                    hf_hub_download(MODEL_REPO, WEIGHTS_FILE, revision=MODEL_REVISION)
                )
            )
            # `.to()` before the first caption, because Moondream allocates its
            # KV cache lazily on whichever device the model is on by then.
            self._model = model.to(self._device).eval()

    def unload(self) -> None:
        with self._lock:
            self._model = None
            # Dropping the reference frees the tensors, but torch keeps the
            # freed blocks in its caching allocator; without this the VRAM
            # stays charged to this process. Nothing in PixlStash calls
            # unload() on a third-party plugin, so the callers are
            # delete_artifact() and this repository's contract tests.
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def is_loaded(self) -> bool:
        return self._model is not None

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def needs_download(self, parameters: dict[str, Any] | None = None) -> bool:
        return _cached_weights() is None

    def download(
        self,
        parameters: dict[str, Any] | None = None,
        progress_callback=None,
    ) -> None:
        """Fetch the weights. Runs on a background thread PixlStash owns.

        ``progress_callback`` is part of the signature but goes unused:
        PixlStash calls ``download()`` with no arguments, and
        ``snapshot_download`` reports its own progress to the server console.
        """
        snapshot_download(
            MODEL_REPO,
            revision=MODEL_REVISION,
            ignore_patterns=IGNORE_PATTERNS,
        )

    def list_downloaded_artifacts(self) -> list[dict[str, Any]]:
        path = _cached_weights()
        if path is None:
            return []
        try:
            size = os.path.getsize(path)
        except OSError:
            return []
        return [
            {
                "name": ARTIFACT_NAME,
                "label": f"{MODEL_REPO} @ {MODEL_REVISION}",
                "size_bytes": size,
            }
        ]

    def delete_artifact(self, name: str) -> None:
        """Remove the cached weights, and free them if they are loaded.

        This deletes the revision from the shared HuggingFace cache, which is
        the only place it exists: it is the same cache PixlStash's model shelf
        scans, and another tool pointed at the same cache loses the weights
        too. Scanning that cache is worth it here, unlike on the polled paths
        above, because deleting is a button press rather than a poll.
        """
        if name != ARTIFACT_NAME:
            raise ValueError(f"Unknown artifact {name!r}")
        cache = scan_cache_dir()
        hashes = [
            revision.commit_hash
            for repo in cache.repos
            if repo.repo_id == MODEL_REPO
            for revision in repo.revisions
            if MODEL_REVISION in revision.refs
        ]
        if not hashes:
            raise ValueError(f"Artifact {name!r} is not downloaded")
        self.unload()
        cache.delete_revisions(*hashes).execute()

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def generate_descriptions(
        self,
        image_paths: list[str],
        parameters: dict[str, Any],
        stop_event=None,
    ) -> dict[str, str | None]:
        """Return one description per path. ``None`` marks a failed image.

        Moondream has no batch API, so this is a plain loop.
        """
        # Saved settings are validated by name but never by type, so read them
        # defensively. Note `.get(key, default)` rather than `.get(key) or
        # default`, which would turn a deliberate 0 into the default.
        mode = parameters.get("mode", DEFAULT_MODE)
        length = parameters.get("length", DEFAULT_LENGTH)
        if length not in LENGTHS:
            length = DEFAULT_LENGTH
        question = parameters.get("question", DEFAULT_QUESTION)
        if not isinstance(question, str) or not question.strip():
            question = DEFAULT_QUESTION
        try:
            max_tokens = int(parameters.get("max_tokens", DEFAULT_MAX_TOKENS))
        except (TypeError, ValueError):
            max_tokens = DEFAULT_MAX_TOKENS
        # Clamped to the bounds the schema declares, because the host validates
        # a saved value's name but not its range: a hand-edited settings file
        # holding 10_000_000 would otherwise generate until it hit the context
        # limit, once per picture, and stop_event cannot interrupt one image.
        max_tokens = min(1024, max(1, max_tokens))
        # "variant" has to be present: Moondream reads `settings["variant"]`
        # with a subscript, not a `.get`, so a settings dict without it raises
        # KeyError before it reaches the model.
        settings = {"max_tokens": max_tokens, "variant": None}

        # Bound once, so a delete_artifact() landing mid-batch finishes with the
        # model this batch started on rather than turning the rest into None.
        model = self._model

        results: dict[str, str | None] = {}
        for path in image_paths:
            # stop_event is always None on the description path today; guard the
            # access rather than assume it stays that way.
            if stop_event is not None and stop_event.is_set():
                break
            try:
                with Image.open(path) as handle:
                    # Moondream's crop step wants three channels, and
                    # image_paths may hold a palette PNG, a greyscale scan or a
                    # video file, which raises here and costs one entry.
                    image = handle.convert("RGB")
                if mode == "query":
                    text = model.query(image, question, settings=settings)["answer"]
                else:
                    text = model.caption(image, length=length, settings=settings)[
                        "caption"
                    ]
                # Inside the guard on purpose. `text` is whatever the model
                # handed back, and a non-string would raise on .strip().
                results[path] = text.strip() or None
            except Exception:
                # Model code raises whatever it likes, and raising out of here
                # would lose the captions already generated for this batch.
                results[path] = None
        return results
