#!/usr/bin/env python3
"""Marketplace API — HuggingFace GGUF model search + provider compatibility."""
import os, re, urllib.request, urllib.error, urllib.parse, json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/v1/models/marketplace", tags=["marketplace"])

HF_API = "https://huggingface.co/api"
HFHeaders = {"Accept": "application/json"}
if token := os.environ.get("HF_TOKEN", ""):
    HFHeaders["Authorization"] = f"Bearer {token}"

_providers: dict = {}


# ─── Helpers ────────────────────────────────────────────────────────────────────

def hf_get(path: str) -> dict:
    url = f"{HF_API}/{path}"
    req = urllib.request.Request(url, headers=HFHeaders)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"HF error {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise HTTPException(status_code=502, detail=f"HF unreachable: {e}")


def parse_params(model_id: str) -> Optional[float]:
    m = re.search(r'(\d+(?:\.\d+)?)[bB]', model_id, re.IGNORECASE)
    return float(m.group(1)) if m else None


QUANT_LEVELS = ["q2_k", "q3_k_m", "q4_0", "q4_k_m", "q5_k_m", "q6_k", "q8_0", "f16", "f32"]


def vram_gb(params_b: float, quant: str) -> float:
    qmap = {"q8_0": 8, "q6_k": 6, "q5_k_m": 5, "q5_k_s": 5,
            "q4_k_m": 4.5, "q4_k_s": 4.3, "q4_0": 4, "q3_k_m": 3.5,
            "q2_k": 2.5, "q1_k": 1.5, "f16": 2, "f32": 4}
    bits = qmap.get(quant.lower(), 4)
    return params_b * bits / 8


def capabilities(model_id: str, tags: list) -> dict:
    id_l = model_id.lower()
    return {
        "coding": any(k in id_l for k in ["cod", "code", "synthia", "starcoder", "deepseek-coder", "qwen2.5-coder", "llama3.1-coder", "phi-coder", "codellama", "phi4"]),
        "reasoning": any(k in id_l for k in ["reason", "logic", "deepseek-r1", "r1"]),
        "tool_use": any(k in id_l for k in ["tool", "function", "gorilla", "athena", "samantha", "agent"]),
        "vision": any(k in id_l for k in ["vl-", "vision", "llava", "internvl", "qwen2-vl"]),
        "embedding": any(k in id_l for k in ["embed", "embedding", "nomic"]),
        "fast": any(k in id_l for k in ["1b", "2b", "0.5b", "0.3b", "nano", "tiny", "gemma-1b", "gemma-2b", "smollm"]),
        "chat": any(t in tags for t in ["text-generation", "conversational", "causal-lm"]),
    }


def available_quants(siblings: list) -> list:
    quants = set()
    for s in siblings:
        fname = s.get("rfilename", "")
        if not fname.endswith(".gguf"):
            continue
        q = re.search(r'-Q(\d+[_\w]+)', fname)
        if q:
            quants.add("Q" + q.group(1).replace("_", "-"))
    return sorted(quants, key=lambda x: QUANT_LEVELS.index(x.lower()) if x.lower() in QUANT_LEVELS else 99)


def _build_provider_profile(host: str, port: int, label: str) -> dict:
    base = f"http://{host}:{port}"
    ram_gb = 64
    try:
        req = urllib.request.Request(f"{base}/api/v1/system", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            sd = json.loads(r.read())
            ram_gb = sd.get("memory", {}).get("total_ram_gb", 64)
    except:
        pass
    return {"endpoint_id": label, "name": label, "api_base": base,
            "ram_gb": ram_gb, "gpu_vram_gb": 0, "max_context": 32768}


async def _probe_providers():
    global _providers
    # 1. Load one-time probed hardware profiles from JSON
    hw_path = os.path.expanduser("~/.pacp/config/provider_hardware.json")
    if os.path.exists(hw_path):
        try:
            with open(hw_path) as f:
                for prof in json.load(f).get("providers", []):
                    if prof.get("status") == "ok":
                        ep_id = prof.get("endpoint_id", prof.get("name", ""))
                        _providers[ep_id] = prof
        except Exception:
            pass
    # 2. Live-probe localhost LM Studio
    try:
        req = urllib.request.Request("http://localhost:1234/api/v1/models", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            json.loads(r.read())
            _providers["local-PAC"] = _build_provider_profile("localhost", 1234, "local-PAC")
    except:
        pass


def _fetch_siblings(model_id: str) -> list:
    """Fetch siblings from model detail endpoint."""
    try:
        m = hf_get(f"models/{urllib.parse.quote(path)}")
        return m.get("siblings", [])
    except:
        return []


def _gguf_files(model_id: str, siblings: list, _depth: int = 0) -> list:
    """Return GGUF files, fetching detail once if siblings are empty."""
    if siblings:
        return [s for s in siblings if s.get("rfilename", "").endswith(".gguf")]
    # Fetch detail once if not already fetched (prevent recursion loop)
    if _depth == 0:
        return _gguf_files(model_id, _fetch_siblings(model_id), _depth=1)
    return []


# ─── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/search")
async def search_models(
    q: str = "",
    limit: int = 20,
    sort: str = "downloads",
    capability: str | None = None,
):
    params = [("search", q), ("direction", "-1"), ("limit", limit), ("sort", sort)]
    qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params if v)
    url = f"{HF_API}/models?{qs}"
    req = urllib.request.Request(url, headers=HFHeaders)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = json.loads(r.read())
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    results = []
    for m in raw[:limit]:
        model_id = m.get("id", "")
        # Try siblings from search result first, fall back to detail fetch
        siblings = m.get("siblings", [])
        gguf_files = [s for s in siblings if s.get("rfilename", "").endswith(".gguf")] if siblings else []
        if not gguf_files:
            gguf_files = _gguf_files(model_id, [])
        if not gguf_files:
            continue
        tags = m.get("tags", [])
        params_b = parse_params(model_id)
        caps = capabilities(path, tags)
        if capability and capability not in ("all", "any") and not caps.get(capability, False):
            continue
        results.append({
            "model_id": path,
            "author": m.get("author", ""),
            "downloads": m.get("downloads", 0),
            "likes": m.get("likes", 0),
            "tags": tags,
            "last_modified": m.get("lastModified", ""),
            "capabilities": caps,
            "params_b": params_b,
            "vram_q4_k_m_gb": vram_gb(params_b, "q4_k_m") if params_b else None,
            "available_quants": available_quants(gguf_files),
            "gated": m.get("gated", False),
            "private": m.get("private", False),
        })
    return {"results": results, "total": len(results), "query": q}


@router.get("/model/{path:path}")
async def model_detail(path: str):
    import urllib.parse
    if not _providers:
        await _probe_providers()
    try:
        m = hf_get(f"models/{urllib.parse.quote(path)}")
    except HTTPException:
        raise HTTPException(status_code=404, detail="Model not found")

    siblings = m.get("siblings", [])
    tags = m.get("tags", [])
    params_b = parse_params(m.get("id", path))

    readme_preview = None
    try:
        rm_req = urllib.request.Request(
            f"https://huggingface.co/{path}/raw/main/README.md",
            headers={"Accept": "text/plain"}
        )
        with urllib.request.urlopen(rm_req, timeout=10) as r:
            readme_preview = r.read().decode("utf-8", "ignore")[:1500]
    except:
        pass

    gguf_files = [s for s in siblings if s.get("rfilename", "").endswith(".gguf")]
    quants_avail = available_quants(gguf_files)

    scores = []
    for ep_id, prof in _providers.items():
        ram = prof.get("ram_gb", 64)
        gpu = prof.get("gpu_vram_gb", 0)
        total = ram + gpu

        if not params_b:
            scores.append({"endpoint_id": ep_id, "provider_name": prof["name"],
                "api_base": prof["api_base"], "can_run": False,
                "reason": "Unknown model size", "available_quants": quants_avail,
                "speed_category": "unknown", "estimated_vram_gb": None, "quant_recommended": None})
            continue

        best_q, best_needed = None, None
        for q in QUANT_LEVELS:
            needed = vram_gb(params_b, q)
            if needed <= total:
                best_q, best_needed = q, needed
                break

        if not best_q:
            smallest = vram_gb(params_b, "q2_k")
            scores.append({"endpoint_id": ep_id, "provider_name": prof["name"],
                "api_base": prof["api_base"], "can_run": False,
                "reason": f"Even Q2_K needs ~{smallest:.0f}GB, provider has {total:.0f}GB",
                "estimated_vram_gb": smallest, "available_quants": quants_avail,
                "speed_category": "impossible", "quant_recommended": None})
            continue

        headroom = total - best_needed
        speed = "fast" if (headroom > 8 and params_b < 3) else ("medium" if headroom > 4 else "slow")
        scores.append({"endpoint_id": ep_id, "provider_name": prof["name"],
            "api_base": prof["api_base"], "can_run": True,
            "reason": f"{best_q.upper()} (~{best_needed:.0f}GB) — {headroom:.0f}GB headroom",
            "estimated_vram_gb": best_needed, "quant_recommended": best_q.upper(),
            "available_quants": quants_avail, "speed_category": speed})

    return {
        "model_id": path,
        "author": m.get("author", ""),
        "downloads": m.get("downloads", 0),
        "likes": m.get("likes", 0),
        "tags": tags,
        "last_modified": m.get("lastModified", ""),
        "pipeline_tag": m.get("pipeline_tag"),
        "capabilities": capabilities(path, tags),
        "params_b": params_b,
        "vram_q4_k_m_gb": vram_gb(params_b, "q4_k_m") if params_b else None,
        "available_quants": quants_avail,
        "provider_scores": scores,
        "gated": m.get("gated", False),
        "private": m.get("private", False),
        "readme_preview": readme_preview,
    }


@router.get("/providers")
async def marketplace_providers():
    if not _providers:
        await _probe_providers()
    return {"providers": list(_providers.values())}


class DownloadOpts(BaseModel):
    model: str
    provider: str = "local-PAC"
    quantization: str | None = None


@router.post("/download")
async def marketplace_download(opts: DownloadOpts):
    if opts.provider not in _providers:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {opts.provider}")
    prof = _providers[opts.provider]
    base = prof["api_base"]
    hf_url = f"https://huggingface.co/{opts.model}"
    quant = opts.quantization or "Q4_K_M"

    payload = json.dumps({"model": hf_url, "quantization": quant}).encode()
    dl_url = f"{base}/api/v1/models/download"
    try:
        req = urllib.request.Request(dl_url, data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise HTTPException(status_code=502, detail=f"Download failed ({e.code}): {body}")
    except urllib.error.URLError as e:
        raise HTTPException(status_code=502, detail=f"Provider unreachable: {e}")
