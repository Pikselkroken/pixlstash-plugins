# OpenAI-Compatible Vision API

Captions your images with a vision model running on a server you already have:
[Ollama](https://ollama.com), [LM Studio](https://lmstudio.ai), llama.cpp's
`llama-server`, vLLM, or anything else that speaks the OpenAI
`/v1/chat/completions` API. Each image is base64-encoded into one request and
the reply is the caption.

**Your images leave PixlStash.** They are sent to whatever the **Endpoint**
setting points at. Pointed at `localhost` that is another process on your own
machine; pointed anywhere else it is a remote service, subject to that
service's terms and privacy policy. The default is a local Ollama.

Nothing is loaded on the PixlStash side: no model download, no `torch`, no
VRAM. That also sidesteps the host gap where nothing calls `unload()` on a
third-party plugin, since there is nothing resident to unload. The model is
loaded and unloaded by the server you point at, which is where it belongs.

## Install

1. Have a server running and a **vision** model pulled on it. With Ollama:

   ```bash
   ollama pull qwen3-vl:8b
   ollama serve            # already running as a service on most installs
   ```

   A text-only model will not caption pictures; it errors or hallucinates.
   Vision models on Ollama include `qwen3-vl` (2b/4b/8b/32b), `qwen2.5vl`
   (3b/7b/32b), `llava` and `minicpm-v`. In LM Studio, load a vision model and
   start the local server from the **Developer** tab.

2. Copy this whole folder into your user captioning plugin directory (take the
   exact path from **Settings → Auto-tagging**) and restart PixlStash Server.

3. Pick **OpenAI-Compatible Vision API** as the description plugin in
   **Settings → Auto-tagging**, and set **Endpoint** and **Model** to match
   your server.

**Captioning plugins need a PixlStash build that loads them.** Discovery is on
`develop` and targeted at 1.10.0; v1.9.0 cannot load this.

## Dependencies

None. Standard library only (`urllib.request`, `base64`, `json`,
`mimetypes`), so there is no `requirements.txt` beside this file.

## Parameters

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `endpoint` | string | `http://localhost:11434/v1` | Base URL of the server. LM Studio is `http://localhost:1234/v1`. `/v1` is appended if you leave it off. Anything unusable, a blank field included, captions nothing and says so in the log, rather than falling back to some other server. It is a base URL, so it may not carry a query string. |
| `model` | string | `qwen3-vl:8b` | Model id as the server reports it. Must be a vision model, and must already be pulled. |
| `prompt` | textarea | `Describe this image in one or two sentences. …` | Instruction sent with every image. |
| `max_tokens` | integer | `256` | Upper bound on caption length, reasoning included. Clamped to 16-4096. See the note below before lowering it. |
| `timeout_seconds` | integer | `120` | Per-image request timeout. Clamped to 5-900. |
| `api_key` | string | *(empty)* | Sent as `Authorization: Bearer …`. Empty for a local Ollama or LM Studio, which need none. |

**The API key is stored in plain text.** Plugin settings live in your
`tagger_settings` JSON, and PixlStash has no secret storage for them, so the
key sits on disk unencrypted and is readable by anything that can read your
config. Leave it empty for a local server. If you do point this at a hosted
endpoint, use a key you can revoke, scoped to nothing else. The key is sent to
whatever **Endpoint** currently says, so re-check that field before saving a
key; over plain `http://` it also crosses the network in the clear, which is
fine to `localhost` and not fine beyond it. Two ways the key could have gone
somewhere else are closed deliberately: redirects are refused rather than
followed, so a server cannot bounce it to a host you did not name, and
`http_proxy`, `https_proxy` and `ALL_PROXY` are ignored, so a proxy variable in
PixlStash's environment cannot route the request (and the image) through a host
that is not the one you typed. If you need a proxy, name it in **Endpoint**.

The clamps are silent: a `max_tokens` of 10000 saved by hand becomes 4096, and
a value that is not a number at all falls back to the default. Nothing warns
you, so read the ranges above rather than the settings file.

## Behaviour worth knowing

- **A failure costs one image.** A refused connection, a timeout, an HTTP
  error, a reply in an unexpected shape, an empty caption: each leaves that
  one image without a description, and the rest of the batch is still stored.
  Every one of them is logged with the path and the reason, because from the
  UI they all look identical: a picture with no description.
- **Five failed requests in a row end the batch.** A host that drops packets
  rather than refusing them costs a full timeout per image, and the description
  worker gets no `stop_event` to cancel with, so a dead endpoint would hold it
  for `timeout_seconds` x the batch. After five consecutive request failures
  the remaining images are marked failed without being tried. Fix the endpoint
  and run the batch again. Only requests count: a file that cannot be read, a
  video, and a picture the model answers nothing for are failures for that one
  image and leave the counter alone, because none of them says the server is
  gone.
- **The timeout bounds each socket read, not the whole call.** A server that
  answers slowly enough, byte by byte, can outlast it, and name resolution
  happens before the timeout applies at all, so a hung DNS server is bounded
  only by your resolver's own patience. Bounding the whole call needs a thread
  to cancel from, and this path has nothing to cancel with; the response size
  is capped instead, so a misbehaving server costs time and not memory.
- **A thinking model spends `max_tokens` on its reasoning first.** With
  `qwen3-vl:8b` at 256 the caption comes back fine, but at 20 or 40 the whole
  budget goes to the reasoning block, the caption is empty, and every image
  reports a failure. If captions come back missing for no visible reason,
  raise **Max tokens** before suspecting anything else.
- **Videos are skipped**, since a video cannot go in a chat message. The type
  is decided by the file extension, so a file with no extension, or one your
  system's mime table does not know, is skipped the same way.
- Ollama accepts PNG, JPEG and WebP; other image types are rejected by the
  server and fail per image.
- The reply is read as `choices[0].message.content`, and a server that answers
  with a list of content parts instead of a plain string has its text parts
  joined. Anything else in the reply is a failure for that image.
- **Images are sent at full size.** Nothing is downscaled here, because the
  servers do their own resizing. A 40-megapixel file spends time on base64 and
  on the wire, over localhost included, and is held in memory a few times over
  while the request is built. Downscaling first would need Pillow and a
  judgement call about quality; a smaller model is the cheaper answer.
- **`is_loaded()` reports that the plugin is configured, not that the server
  is up**, and `needs_download()` is always `False`. Neither is a health check,
  and there is no download button: pulling a multi-gigabyte model is the server
  admin's decision, not a button in an image manager. There is nowhere useful
  to put an endpoint check today, either. `is_loaded()` is polled by the
  settings table and called by `plugin_schema()` on the request thread, so a
  network probe there would block the settings screen; and `needs_download()`
  is called by exactly one route, the download route, with no parameters, so a
  check there would test the default endpoint rather than yours and a `True`
  would start a background "download" that does nothing. **A failed request
  says why in the server log** — that is where to look when captions do not
  appear.
- **The model is whatever that tag points at.** `qwen3-vl:8b` on the server
  today and after the next `ollama pull` are not necessarily the same weights,
  so captions are not reproducible across a server-side update. Nothing here
  can pin that; it is the server's to pin.

## Tested against

Ollama 0.32.5 on Linux with `qwen3-vl:8b` on an NVIDIA RTX 5090, driven
straight from Python rather than through PixlStash, since no released
PixlStash loads captioning plugins yet. Captioned a PNG and a JPEG, and
checked: an endpoint written with and without `/v1`, an API key sent to a
server that ignores it, a video path, a file with no extension, a refused
endpoint, an endpoint that blackholes (the batch ended after five failures
rather than eight timeouts), a server answering `302` (refused, and the key
went no further), `http_proxy`, `https_proxy` and `ALL_PROXY` all pointed at a
proxy that logged what it received (it received nothing, and the caption still
came back from the real endpoint), an endpoint that is not an http(s) URL
(nothing sent), and junk in every setting.

The repository's contract tests pass on Python 3.12, but note what that does
and does not mean here: they call `generate_descriptions` with the defaults,
so with a server on `localhost:11434` they perform real inference on the
fixture images, and with no server they take the connection-refused path and
assert only that every path came back mapped to `None`. Neither run checks a
caption. The offline self-check at the bottom of `__init__.py` covers the
settings handling, the reply parsing, and the batch loop with the network and
the disk stubbed out (every path accounted for, the breaker stopping after five
failed requests, and unreadable files not arming it):

```bash
python plugins/captioning/openai_compatible_captioner/__init__.py
```

`pixlstash-cli plugins test` was not run: the published `pixlstash` package
ships no such entry point, and the CLI, like captioning plugin discovery
itself, is on `develop` and unreleased.

LM Studio was not tested. It serves the same API and the same request shape,
and is documented here as the second target rather than as something verified.

## License

MIT, see the [LICENSE](../../../LICENSE) at the repository root. That covers
this plugin's own code and nothing else.

The model does not come from here, so its terms are not this repository's to
state: whichever one you name in **Model** carries its own license, and a
hosted endpoint carries its terms of service on top. The plugin's `models`
header names the default, `qwen3-vl:8b`, which on Ollama is
[Qwen/Qwen3-VL-8B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)
under Apache-2.0. Point the plugin at something else and that entry no longer
describes what you are running, which is also why no revision is pinned: an
Ollama tag resolves on the server, and re-pulling it can change the weights.
