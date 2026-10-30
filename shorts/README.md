# Self-hosted YouTube Shorts Factory

An add-on to ComfyUI-Video-Generalist for **five AI-video Shorts/day**, with **no paid AI inference APIs**. Uses local Ollama/Qwen for storyboarding, ComfyUI for video clips, Kokoro for narration, and FFmpeg for stitched vertical MP4 and SRT captions. You still pay for RunPod compute/storage.

## Before running

1. Deploy the existing RunPod template and verify `curl http://127.0.0.1:8188/system_stats` works. Never expose an unauthenticated ComfyUI or Jupyter instance to the public internet.
2. Choose an installed video-generation workflow in the ComfyUI UI (Wan or LTX), **run it successfully once**, and export it via **Save (API Format)** to `/workspace/shorts-workflow-api.json`. This is essential: different custom nodes/models have different schemas; the controller must not guess them.
3. Put a *prompt-text node*, optional *seed node*, and final *video output node* IDs in `.env`; the prompt node must have `inputs.text`, seed node `inputs.seed`, and the output node must save a video file and expose its filename through `/history` outputs. Check actual node fields in the exported workflow. For workflows that use `inputs.prompt` instead of `inputs.text`, set `SHORTS_PROMPT_FIELD=prompt`; similarly use `SHORTS_SEED_FIELD`.
4. Run `bash shorts/setup.sh`; start Ollama (e.g. `ollama serve` in another terminal) then `ollama pull qwen2.5:7b`. Set up `.env` using `.env.example`. Ollama and ComfyUI should ideally **not** run generation simultaneously on a 24GB GPU; the script runs them sequentially.
5. Try `python shorts/factory.py --count 1 --dry-run` to verify prompts without any GPU video generation. Then run `python shorts/factory.py --count 1` for one full Short. Inspect the video before scheduling.

## Daily production

`python shorts/factory.py --count 5` processes the next five topics from `topics.txt` (cycling through it). Completion markers prevent regenerating the same topic on the same UTC date. The output directory includes `short.mp4`, `narration.wav`, `captions.srt`, and `storyboard.json` for each video.

Schedule on a **running** Pod with cron: `0 2 * * * cd /workspace/ComfyUI-Video-Generalist && /workspace/shorts-venv/bin/python shorts/factory.py --count 5 >> /workspace/shorts-output/daily.log 2>&1`. Ensure environment variables are available via the `.env` file; the script loads it without a third-party dependency. A stopped Pod cannot execute cron. Start with manual batches before unattended scheduling.

## Limitations

- The exported video workflow must match the actual ComfyUI node types and models. Some video output nodes do not expose file metadata; those need a matching adapter.
- One generated clip per scene, five scenes per Short. The final duration is five times the generated clip duration; the narration is mixed and captions use estimated sentence timing, not Whisper forced alignment.
- RunPod storage, model licenses, YouTube review, and GPU runtime require your attention. Do not automatically upload without reviewing content accuracy and licensing.
- No API authentication is implemented for ComfyUI; bind it locally or restrict it to a trusted network.
