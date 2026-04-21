#!/usr/bin/env python3
"""智能模型选择器 - 根据可用 API Key 动态选择最佳 AI 模型"""

import os
import sys
import json
import time
import re
from typing import Optional, Tuple, List, Dict

LEADERBOARD_CACHE = ".leaderboard_cache.json"
CUSTOM_PROVIDER_INFO = {
    "dmxapi": {"base_url": "https://api.dmxapi.com/v1", "api_key_env": "DMXAPI_API_KEY"},
    "qiniu": {"base_url": "https://api.qnaigc.com/v1", "api_key_env": "QINIU_API_KEY"},
    "xai": {"base_url": "https://api.x.ai/v1", "api_key_env": "XAI_API_KEY"},
    "bailian": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "BAILIAN_API_KEY"},
    "moonshot": {"base_url": "https://api.moonshot.cn/v1", "api_key_env": "MOONSHOT_API_KEY"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY"},
    "siliconflow": {"base_url": "https://api.siliconflow.cn/v1", "api_key_env": "SILICONFLOW_API_KEY"},
    "modelscope": {"base_url": "https://api.modelscope.cn/v1", "api_key_env": "MODELSCOPE_API_KEY"},
    "atomgit": {"base_url": "https://api-ai.gitcode.com/v1", "api_key_env": "ATOMGIT_API_KEY"},
    "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4/", "api_key_env": "ZHIPU_API_KEY"},
    "nvidia-nim": {"base_url": "https://integrate.api.nvidia.com/v1", "api_key_env": "NVIDIA_NIM_API_KEY"},
    "minimax": {"base_url": "https://api.minimax.chat/v1", "api_key_env": "MINIMAX_API_KEY"},
    "github_copilot": {"base_url": "", "api_key_env": "GITHUB_TOKEN"},
}

DEFAULT_MODELS = {
    "dmxapi": ["claude-sonnet-4-20250514", "gpt-4.1", "gemini-2.5-pro-preview-05-06"],
    "qiniu": ["kimi/kimi-k2.5", "deepseek/DeepSeek-V3-0324", "Qwen/Qwen3-235B-A22B"],
    "xai": ["grok-3-latest", "grok-3-mini-latest"],
    "openrouter": ["anthropic/claude-sonnet-4", "google/gemini-2.5-pro-preview"],
    "openai": ["gpt-4.1", "gpt-4o"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "zen": ["mimo-v2-pro-free"],
    "minimax": ["MiniMax-M2.7"],
    "moonshot": ["moonshot-v1-auto"],
    "bailian": ["qwen-max", "qwen-plus"],
    "modelscope": ["Qwen/Qwen3-235B-A22B"],
    "siliconflow": ["deepseek-ai/DeepSeek-V3"],
    "atomgit": ["zai-org/GLM-5"],
    "zhipu": ["glm-4-plus"],
    "nvidia-nim": ["deepseek-ai/deepseek-v3"],
    "github_copilot": ["gpt-5.4", "claude-opus-4.7", "gpt-5.4-mini", "gpt-5.2-codex"],
}

MINIMAX_ALLOWED = ["minimax-ccp-2.7", "minimax-m2.7"]
MINIMAX_BLOCKED = ["highspeed", "m2.5", "m1.5", "abab"]

def split_env(name: str, default: str = "") -> List[str]:
    raw = os.getenv(name, "").strip()
    src = raw if raw else default
    return [m.strip() for m in src.split(",") if m.strip()]

def load_cached_top20() -> Tuple[Optional[set], float]:
    if not os.path.exists(LEADERBOARD_CACHE):
        return None, 0
    try:
        with open(LEADERBOARD_CACHE, "r") as f:
            data = json.load(f)
        return set(data.get("top20", [])), data.get("timestamp", 0)
    except Exception:
        return None, 0

def save_cached_top20(top20: set):
    try:
        with open(LEADERBOARD_CACHE, "w") as f:
            json.dump({"timestamp": time.time(), "top20": sorted(top20)}, f, indent=2)
    except Exception:
        pass

def fetch_leaderboard_top20() -> Optional[set]:
    try:
        import requests
        print("[pick_best_model] 爬取排行榜...", file=sys.stderr)
        resp = requests.get(
            "https://artificialanalysis.ai/leaderboards/models",
            headers={"User-Agent": "LobeChat-PickModel/2.0"},
            timeout=15
        )
        if resp.status_code != 200:
            return load_cached_top20()[0]
        
        models_with_scores = []
        matches = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', resp.text)
        for block in matches:
            block = block.replace('\\"', '"')
            for m in re.finditer(r'"slug":"([a-z0-9\-.]+)"', block):
                slug = m.group(1)
                after = block[m.end(): m.end() + 200]
                score_match = re.search(r'"quality_score"\s*:\s*([0-9.]+)', after)
                score = float(score_match.group(1)) if score_match else 0.0
                models_with_scores.append((slug, score))
        
        if models_with_scores:
            slug_best = {}
            for slug, score in models_with_scores:
                if slug not in slug_best or score > slug_best[slug]:
                    slug_best[slug] = score
            sorted_models = sorted(slug_best.items(), key=lambda x: x[1], reverse=True)
            top_models = set(slug for slug, _ in sorted_models[:30])
            save_cached_top20(top_models)
            print(f"[pick_best_model] 排行榜爬取成功: {len(top_models)} 个模型", file=sys.stderr)
            return top_models
    except Exception as e:
        print(f"[pick_best_model] 排行榜爬取失败: {e}", file=sys.stderr)
    
    cached, ts = load_cached_top20()
    if cached:
        days_old = (time.time() - ts) / 86400
        print(f"[pick_best_model] 使用 {days_old:.1f} 天前的缓存", file=sys.stderr)
    return cached

def is_top20_match(model_id: str, top20: Optional[set]) -> bool:
    if not top20:
        return True
    base = model_id.lower().replace("-free", "").replace("_free", "")
    core = base.split("/")[-1] if "/" in base else base
    core_nodot = core.replace("-", "").replace(".", "")
    for slug in top20:
        slug_nodot = slug.replace("-", "").replace(".", "")
        if slug_nodot in core_nodot or core_nodot in slug_nodot:
            return True
    return False

def is_minimax_allowed(model_id: str) -> bool:
    mid = model_id.lower()
    if "minimax" not in mid:
        return True
    if any(b in mid for b in MINIMAX_BLOCKED):
        return False
    return any(a in mid for a in MINIMAX_ALLOWED)

def pick_model():
    top20 = fetch_leaderboard_top20()
    
    env = os.environ
    # 调试信息：检查关键环境变量
    debug_keys = ["DMXAPI_API_KEY", "QINIU_API_KEY", "DEEPSEEK_API_KEY", "MINIMAX_API_KEY", "MINIMAX_CODING_PLAN_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"]
    for key in debug_keys:
        if key in env and env[key].strip():
            print(f"[pick_best_model] 检测到环境变量: {key}", file=sys.stderr)
    providers = []
    
    if env.get("DMXAPI_API_KEY", "").strip():
        models = split_env("DMXAPI_MODEL_LIST", "claude-sonnet-4-20250514,gpt-4.1")
        providers.append(("dmxapi", models[0], models[-1], models))
    
    if env.get("QINIU_API_KEY", "").strip():
        models = split_env("QINIU_MODEL_LIST", "Qwen/Qwen3-235B-A22B")
        providers.append(("qiniu", models[0], models[-1], models))
    
    if env.get("XAI_API_KEY", "").strip():
        models = split_env("XAI_MODEL_LIST", "grok-3-latest,grok-3-mini-latest")
        providers.append(("xai", models[0], models[-1], models))
    
    if env.get("OPENROUTER_API_KEY", "").strip():
        models = split_env("OPENROUTER_MODEL_LIST", "anthropic/claude-sonnet-4,google/gemini-2.5-pro-preview")
        providers.append(("openrouter", models[0], models[-1], models))
    
    if env.get("OPENAI_API_KEY", "").strip():
        models = split_env("OPENAI_MODEL_LIST", "gpt-4.1,gpt-4o")
        providers.append(("openai", models[0], models[-1], models))
    
    if env.get("DEEPSEEK_API_KEY", "").strip():
        models = split_env("DEEPSEEK_MODEL_LIST", "deepseek-chat,deepseek-reasoner")
        providers.append(("deepseek", models[0], models[-1], models))
    
    if env.get("ZEN_API_KEY", "").strip():
        models = split_env("ZEN_MODEL_LIST", "mimo-v2-pro-free")
        providers.append(("zen", models[0], models[-1], models))
    
    if env.get("BAILIAN_API_KEY", "").strip():
        models = split_env("BAILIAN_MODEL_LIST", "qwen-max,qwen-plus")
        providers.append(("bailian", models[0], models[-1], models))
    
    if env.get("MOONSHOT_API_KEY", "").strip():
        models = split_env("MOONSHOT_MODEL_LIST", "moonshot-v1-auto")
        providers.append(("moonshot", models[0], models[-1], models))
    
    if env.get("SILICONFLOW_API_KEY", "").strip():
        models = split_env("SILICONFLOW_MODEL_LIST", "deepseek-ai/DeepSeek-V3")
        providers.append(("siliconflow", models[0], models[-1], models))
    
    if env.get("MODELSCOPE_API_KEY", "").strip():
        models = split_env("MODELSCOPE_MODEL_LIST", "Qwen/Qwen3-235B-A22B")
        providers.append(("modelscope", models[0], models[-1], models))
    
    if env.get("ATOMGIT_API_KEY", "").strip():
        models = split_env("ATOMGIT_MODEL_LIST", "zai-org/GLM-5")
        providers.append(("atomgit", models[0], models[-1], models))
    
    if env.get("ZHIPU_API_KEY", "").strip():
        models = split_env("ZHIPU_MODEL_LIST", "glm-4-plus")
        providers.append(("zhipu", models[0], models[-1], models))
    
    if env.get("NVIDIA_NIM_API_KEY", "").strip():
        models = split_env("NVIDIA_NIM_MODEL_LIST", "deepseek-ai/deepseek-v3")
        providers.append(("nvidia-nim", models[0], models[-1], models))
    
    # 支持 MINIMAX_API_KEY 和 MINIMAX_CODING_PLAN_API_KEY
    minimax_key = env.get("MINIMAX_API_KEY", "").strip() or env.get("MINIMAX_CODING_PLAN_API_KEY", "").strip()
    if minimax_key:
        # 设置 MINIMAX_API_KEY 环境变量，确保后续使用
        os.environ["MINIMAX_API_KEY"] = minimax_key
        models = split_env("MINIMAX_MODEL_LIST", "MiniMax-M2.7")
        providers.append(("minimax", models[0], models[-1], models))
    
    if env.get("BLTCY_API_KEY", "").strip():
        models = split_env("BLTCY_MODEL_LIST", "claude-sonnet-4-20250514")
        providers.append(("bltcy", models[0], models[-1], models))
    
    # GitHub Copilot fallback (uses GITHUB_TOKEN or GH_TOKEN)
    if env.get("GITHUB_TOKEN", "").strip() or env.get("GH_TOKEN", "").strip():
        models = split_env("GITHUB_COPILOT_MODEL_LIST", "gpt-5.4,claude-opus-4.7,gpt-5.4-mini,gpt-5.2-codex")
        providers.append(("github_copilot", models[0], models[-1], models))
    
    if not providers:
        print("NO_MODEL_AVAILABLE", file=sys.stderr)
        return "", "", "", []
    
    # 优先级排序 (根据用户配置调整)
    priority_order = {
        "atomgit": 1,      # 千帆 GLM-5 (大 Agent 优先)
        "qiniu": 2,        # 千帆 DeepSeek
        "deepseek": 3,     # DeepSeek 官方
        "minimax": 4,      # MiniMax 2.7 (小 Agent 优先)
        "bailian": 5,      # 千帆其他 (阿里百炼)
        "moonshot": 6,     # 千帆 Kimi
        "zhipu": 7,        # 智谱 AI
        "dmxapi": 8,
        "openai": 9,
        "openrouter": 10,
        "xai": 11,
        "zen": 12,
        "siliconflow": 13,
        "modelscope": 14,
        "nvidia-nim": 15,
        "bltcy": 16,
        "github_copilot": 999,
    }
    
    # 如果是 --small 模式，调整优先级让 minimax 最优先，atomgit 最后
    if "--small" in sys.argv:
        priority_order["minimax"] = 1
        priority_order["atomgit"] = 100  # 降低优先级
    
    providers.sort(key=lambda x: priority_order.get(x[0], 999))
    # 调试信息：显示可用 providers
    if providers:
        print(f"[pick_best_model] 可用 providers: {[p[0] for p in providers]}", file=sys.stderr)
    
    provider, model, small, models_list = providers[0]
    print(f"[pick_best_model] 选择: {provider}/{model} (small: {small})", file=sys.stderr)
    return provider, model, small, models_list

if __name__ == "__main__":
    provider, model, small, models_list = pick_model()
    
    if not model:
        print("NO_MODEL_AVAILABLE")
        sys.exit(1)
    
    if "--opencode-config" in sys.argv:
        provider_config = {}
        if provider in CUSTOM_PROVIDER_INFO:
            info = CUSTOM_PROVIDER_INFO[provider]
            if provider == "github_copilot":
                provider_config = {
                    "npm": "@opencode/plugin-github-copilot",
                    "models": {m: {} for m in models_list}
                }
            else:
                provider_config = {
                    "npm": "@ai-sdk/openai-compatible",
                    "options": {
                        "baseURL": info["base_url"],
                        "apiKey": "{env:" + info["api_key_env"] + "}"
                    },
                    "models": {m: {} for m in models_list}
                }
        elif models_list:
            provider_config = {"models": {m: {} for m in models_list}}
        
        config = {
            "$schema": "https://opencode.ai/config.json",
            "plugin": ["oh-my-openagent"],
            "provider": {provider: provider_config} if provider_config else {},
            "model": f"{provider}/{model}",
            "small_model": f"{provider}/{small}"
        }
        print(json.dumps(config, indent=2))
    else:
        target = small if "--small" in sys.argv else model
        print(f"{provider}/{target}")
