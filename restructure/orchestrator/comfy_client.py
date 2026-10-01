"""ComfyUI client — generates figures for developed graph nodes.

ComfyUI runs as a service inside the single docker-compose stack. For each
sufficiently-developed reasoning node we submit PAPER_IMAGE_COUNT prompts built
from the node's idea text, and — when the node cites a paper that ships its own
figures — we feed one of that paper's OWN images back in as an img2img
reference (per the spec: "take as reference its own images that is within the
paper we used on that graph node").

The default workflow is a standard SDXL txt2img / img2img graph expressed in
ComfyUI's /prompt API format. If the configured checkpoint is absent ComfyUI
will error; the client degrades gracefully and records the failure rather than
crashing the pipeline.
"""
from __future__ import annotations

import io
import json
import time
import urllib.parse
import uuid
from pathlib import Path

import requests

import config


def _txt2img_workflow(prompt: str, seed: int) -> dict:
    return {
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": config.COMFY_STEPS, "cfg": 7.0,
            "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "4": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": config.COMFY_CHECKPOINT}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": config.COMFY_WIDTH, "height": config.COMFY_HEIGHT, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "blurry, low quality, watermark, text artifacts", "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "paper", "images": ["8", 0]}},
    }


def _img2img_workflow(prompt: str, seed: int, ref_name: str) -> dict:
    wf = _txt2img_workflow(prompt, seed)
    # Replace the empty latent with an encoded reference image.
    wf["10"] = {"class_type": "LoadImage", "inputs": {"image": ref_name}}
    wf["11"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["4", 2]}}
    wf["3"]["inputs"]["latent_image"] = ["11", 0]
    wf["3"]["inputs"]["denoise"] = 0.65
    return wf


def _upload_reference(ref_path: Path) -> str | None:
    try:
        with ref_path.open("rb") as fh:
            files = {"image": (ref_path.name, fh, "application/octet-stream")}
            r = requests.post(f"{config.COMFYUI_URL}/upload/image",
                              files=files, data={"overwrite": "true"}, timeout=60)
        r.raise_for_status()
        return r.json().get("name", ref_path.name)
    except Exception as e:
        print(f"  [comfy] reference upload failed: {e}")
        return None


def _submit(workflow: dict) -> str | None:
    client_id = str(uuid.uuid4())
    try:
        r = requests.post(f"{config.COMFYUI_URL}/prompt",
                          json={"prompt": workflow, "client_id": client_id}, timeout=60)
        r.raise_for_status()
        return r.json()["prompt_id"]
    except Exception as e:
        print(f"  [comfy] submit failed: {e}")
        return None


def _wait_and_fetch(prompt_id: str, dst: Path, timeout: int = 300) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            h = requests.get(f"{config.COMFYUI_URL}/history/{prompt_id}", timeout=30).json()
        except Exception:
            time.sleep(2)
            continue
        entry = h.get(prompt_id)
        if not entry:
            time.sleep(2)
            continue
        for node in entry.get("outputs", {}).values():
            for img in node.get("images", []):
                q = urllib.parse.urlencode({
                    "filename": img["filename"], "subfolder": img.get("subfolder", ""),
                    "type": img.get("type", "output")})
                try:
                    data = requests.get(f"{config.COMFYUI_URL}/view?{q}", timeout=60).content
                    dst.write_bytes(data)
                    return True
                except Exception:
                    pass
        return False
    return False


def health() -> bool:
    try:
        requests.get(f"{config.COMFYUI_URL}/system_stats", timeout=10).raise_for_status()
        return True
    except Exception:
        return False


def generate_for_node(node_id: str, prompt: str, reference_images: list[str] | None = None) -> list[str]:
    """Generate PAPER_IMAGE_COUNT images for one node. Returns saved paths."""
    saved: list[str] = []
    references = reference_images or []
    for i in range(config.PAPER_IMAGE_COUNT):
        seed = (abs(hash((node_id, i))) % (2**31))
        ref_name = None
        if references:
            ref = Path(references[i % len(references)])
            if ref.exists():
                ref_name = _upload_reference(ref)
        workflow = (_img2img_workflow(prompt, seed, ref_name)
                    if ref_name else _txt2img_workflow(prompt, seed))
        pid = _submit(workflow)
        if not pid:
            continue
        dst = config.FIGURES_DIR / f"{node_id}_img{i}.png"
        if _wait_and_fetch(pid, dst):
            saved.append(str(dst))
            print(f"  [comfy] saved {dst.name}" + (f" (ref: {ref_name})" if ref_name else ""))
    return saved
