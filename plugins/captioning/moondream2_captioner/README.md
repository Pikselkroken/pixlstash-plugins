# Moondream2 Captioner

Describes a picture with
[Moondream2](https://huggingface.co/vikhyatk/moondream2), or answers a question
you type once and get answered for every picture in the batch.

It sits between the two captioners PixlStash already ships: Florence-2 writes
short literal captions, JoyCaption writes long ones and will go explicit,
and Moondream writes a couple of natural sentences about what is happening in
the frame. It is general-purpose, describing scenes, objects and composition.

The model is about 1.9B parameters, and loads in bfloat16 straight from the
checkpoint: 3.85 GB on disk, the same again on the device, plus Moondream's KV
cache. That matters more than it sounds: **nothing in PixlStash calls
`unload()` on a third-party plugin**, so once a batch has run the model stays
resident for the life of the server process, next to Florence-2 and the face
and embedding models. Deleting the artifact from **Settings → Auto-tagging**
does free it.

**Captioning plugins need PixlStash `develop`, targeted at 1.10.0.** No
release loads them, v1.9.0 included.

## Install

Copy this whole folder into your user captioning plugin directory (take the
exact path from **Settings → Auto-tagging**) and restart PixlStash Server.
Then pick **Moondream2** as the description plugin in
**Settings → Auto-tagging**, and press its download button before the first
run.

Two things to know before you do:

- **It runs the model's own Python.** Moondream ships as `trust_remote_code`,
  so transformers downloads `.py` files from the model repository and executes
  them inside the server process. PixlStash already runs this plugin
  unsandboxed in that process, so it is not a new kind of trust, but it is one
  more repository. The revision is pinned to `2025-06-21` rather than tracking
  `main`, so an upstream change cannot arrive silently.
- **It downloads about 3.9 GB on first use.** The download button fetches it
  ahead of time; without it, the first caption blocks on the download. The
  `.gguf` copies in the repository, another 3.75 GB, are skipped.

## Dependencies

None beyond what PixlStash already installs. `requirements.txt` lists what the
plugin imports (`torch`, `transformers`, `huggingface_hub`, `safetensors`,
`Pillow`) so it can be installed into a bare environment; **do not pip-install
it into a working PixlStash environment**, since it would happily move `torch`
underneath one.

Moondream's own `requirements.txt` also lists `pyvips`, which it uses for
faster crop resizing when it can import it and falls back to Pillow when it
cannot. Installing it is optional.

## Parameters

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `mode` | select | `caption` | `caption` describes the picture; `query` runs the question below against every picture instead. |
| `length` | select | `normal` | `short` (one sentence), `normal` (a few sentences) or `long` (a paragraph or two). Ignored in question mode. |
| `question` | textarea | `Describe what is happening in this image.` | Asked of every picture in question mode, for example "What is the subject wearing?". Ignored in caption mode. |
| `max_tokens` | integer | `256` | Upper bound on the generated text. `long` wants more than the default to finish a paragraph. |

Moondream has no batch API, so pictures are captioned one at a time. A picture
that fails, including a video file, which PixlStash may hand a description
plugin, gets no description; the rest of the batch is still stored.

## Tested against

- Moondream2 `vikhyatk/moondream2` at revision `2025-06-21`
- PixlStash `develop`, on `torch` 2.13.0+cu130 and `transformers` 5.12.1
- Linux, NVIDIA RTX 5090, CUDA. Roughly 7 s to load, and 0.2 s to 1.2 s per
  picture depending on the length asked for.

`pixlstash-cli plugins test` passes, both bare and with `--image`: the plugin
registers as `moondream2`, all four parameters render, and it captions a real
picture through PixlStash's own loader.

Exercised through the plugin's own interface too: the download quartet,
`init()` twice, each mode and length, junk parameter values, an out-of-range
`max_tokens`, an empty batch, a non-image path, a model stubbed to return
something that is not a string, and a `stop_event` that is already set. On
`cuda` and on `cpu`. Not yet exercised inside a running PixlStash server, so
the settings dialog is built from a schema `plugins test` says will render
rather than one that has been seen on screen.

The repository's contract tests skip this plugin, because CI installs nothing
from a plugin's `requirements.txt` and the plugin cannot be imported without
`torch`. That is the documented state of affairs for any plugin wrapping a
model, and it is why the list above is spelled out.

**Note for anyone reading `__init__.py` and wondering:** the model is built and
then filled from the checkpoint by hand instead of via
`AutoModelForCausalLM.from_pretrained`. That is not style. On transformers 5,
`from_pretrained` first raises `AttributeError` on
`all_tied_weights_keys` (Moondream never calls `post_init()`), and once that is
patched around it constructs the model on the meta device, which leaves
Moondream's non-persistent causal-mask buffer uninitialised. The model then
loads without complaint, passes a weights-versus-checkpoint comparison, and
captions every picture with fluent nonsense. `init()` documents this at
length, because it is a silent wrong answer rather than a crash.

## License

The plugin is MIT, see the [LICENSE](../../../LICENSE) at the repository root.

Moondream2 itself is **Apache 2.0**, and is downloaded from HuggingFace on
first use. It runs locally: no image leaves your machine.
