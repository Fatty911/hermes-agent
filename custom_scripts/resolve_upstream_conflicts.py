#!/usr/bin/env python3
"""
Lobe-Chat 上游同步冲突自动解决脚本 (Track 2)

综合了以下仓库的优点：
- AutoBuild_OpenWrt: 多Provider支持、智能模型选择、实时排行榜爬取
- crawl_cars: 简洁的Provider发现、JSON响应解析
- lobe-chat: Node.js实现参考、BLTCY代理支持

使用方法：
    python resolve_upstream_conflicts.py

环境变量：
    DMXAPI_API_KEY        - DMXAPI API key (推荐，免费)
    QINIU_API_KEY         - 七牛云 API key
    XAI_API_KEY           - xAI Grok API key
    BLTCY_API_KEY         - BLTCY代理 API key
    BLTCY_PROXY_URL       - BLTCY代理 URL
    OPENROUTER_API_KEY    - OpenRouter API key
    OPENAI_API_KEY        - OpenAI API key
    DEEPSEEK_API_KEY      - DeepSeek API key
    ZEN_API_KEY           - ZEN API key
    *_MODEL_LIST          - 各提供商的模型列表 (可选)
"""

import os
import sys
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Optional, Dict, List, Tuple

# ============================================================================
# 1. Provider 配置
# ============================================================================

PROVIDER_BASE_URLS = {
    "DMXAPI": "https://api.dmxapi.com/v1",
    "QINIU": "https://api.qnaigc.com/v1",
    "XAI": "https://api.x.ai/v1",
    "OPENROUTER": "https://openrouter.ai/api/v1",
    "OPENAI": "https://api.openai.com/v1",
    "DEEPSEEK": "https://api.deepseek.com/v1",
    "ZEN": "https://opencode.ai/zen/v1",
    "MINIMAX": "https://api.minimax.chat/v1",
    "MOONSHOT": "https://api.moonshot.cn/v1",
    "BAILIAN": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "MODELSCOPE": "https://api.modelscope.cn/v1",
    "SILICONFLOW": "https://api.siliconflow.cn/v1",
    "ATOMGIT": "https://api-ai.gitcode.com/v1",
    "ZHIPU": "https://open.bigmodel.cn/api/paas/v4/",
    "NVIDIA_NIM": "https://integrate.api.nvidia.com/v1",
}

# 默认模型列表 (2026 最新排行榜)
PROVIDER_DEFAULT_MODELS = {
    "DMXAPI": ["claude-sonnet-4-20250514", "gpt-4.1", "gemini-2.5-pro-preview-05-06"],
    "QINIU": ["Qwen/Qwen3-235B-A22B", "deepseek/DeepSeek-V3-0324"],
    "XAI": ["grok-3-latest", "grok-3-mini-latest"],
    "OPENROUTER": ["anthropic/claude-sonnet-4", "google/gemini-2.5-pro-preview", "openai/gpt-4.1"],
    "OPENAI": ["gpt-4.1", "gpt-4o"],
    "DEEPSEEK": ["deepseek-chat", "deepseek-reasoner"],
    "ZEN": ["mimo-v2-pro-free", "mimo-v2-0317-free"],
    "MINIMAX": ["MiniMax-M2.7"],
    "MOONSHOT": ["moonshot-v1-auto", "moonshot-v1-128k"],
    "BAILIAN": ["qwen-max", "qwen-plus", "qwen-turbo"],
    "MODELSCOPE": ["Qwen/Qwen3-235B-A22B"],
    "SILICONFLOW": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen3-235B-A22B"],
    "ATOMGIT": ["zai-org/GLM-5", "Qwen/Qwen3-235B-A22B"],
    "ZHIPU": ["glm-4-plus", "glm-4"],
    "NVIDIA_NIM": ["deepseek-ai/deepseek-v3", "qwen/qwen3-235b-a22b"],
}

# MiniMax 白名单（防止使用付费/不兼容模型）
MINIMAX_ALLOWED = ["minimax-ccp-2.7", "minimax-ccp2.7", "minimax-m2.7"]
MINIMAX_BLOCKED = ["highspeed", "m2.5", "m1.5", "m1.0", "abab"]

# ============================================================================
# 2. 排行榜爬取
# ============================================================================

LEADERBOARD_CACHE_FILE = ".leaderboard_cache.json"
LEADERBOARD_STALE_DAYS = 14


def fetch_leaderboard_top20() -> Optional[set]:
    """从 Artificial Analysis 爬取排行榜前20模型"""
    try:
        import requests
        
        print("=== 爬取 Artificial Analysis 排行榜 ===")
        url = "https://artificialanalysis.ai/leaderboards/models"
        resp = requests.get(url, headers={"User-Agent": "LobeChat-AutoFix/2.0"}, timeout=15)
        
        if resp.status_code != 200:
            print(f"排行榜爬取失败: HTTP {resp.status_code}")
            return load_cached_leaderboard()
        
        # 提取模型信息
        models_with_scores = []
        matches = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', resp.text)
        
        for block in matches:
            block = block.replace('\\"', '"')
            slug_matches = re.finditer(r'"slug":"([a-z0-9\-.]+)"', block)
            
            for m in slug_matches:
                slug = m.group(1)
                after_slug = block[m.end(): m.end() + 200]
                score_match = re.search(r'"quality_score"\s*:\s*([0-9.]+)', after_slug)
                score = float(score_match.group(1)) if score_match else 0.0
                models_with_scores.append((slug, score))
        
        if models_with_scores:
            # 按分数排序，取前20
            slug_best_score = {}
            for slug, score in models_with_scores:
                if slug not in slug_best_score or score > slug_best_score[slug]:
                    slug_best_score[slug] = score
            
            sorted_models = sorted(slug_best_score.items(), key=lambda x: x[1], reverse=True)
            top20 = set(slug for slug, _ in sorted_models[:20])
            
            # 保存缓存
            save_cached_leaderboard(top20)
            print(f"排行榜爬取成功: {len(top20)} 个模型")
            return top20
            
    except Exception as e:
        print(f"排行榜爬取异常: {e}")
    
    return load_cached_leaderboard()


def load_cached_leaderboard() -> Optional[set]:
    """加载缓存的排行榜"""
    if not os.path.exists(LEADERBOARD_CACHE_FILE):
        return None
    
    try:
        with open(LEADERBOARD_CACHE_FILE, "r") as f:
            data = json.load(f)
        slugs = set(data.get("top20", []))
        ts = data.get("timestamp", 0)
        
        days_old = (time.time() - ts) / 86400
        if days_old > LEADERBOARD_STALE_DAYS:
            print(f"⚠️ 排行榜缓存已 {days_old:.0f} 天未更新")
        else:
            print(f"使用 {days_old:.1f} 天前的排行榜缓存")
        
        return slugs if slugs else None
    except Exception:
        return None


def save_cached_leaderboard(top20: set):
    """保存排行榜缓存"""
    try:
        with open(LEADERBOARD_CACHE_FILE, "w") as f:
            json.dump({"timestamp": time.time(), "top20": sorted(top20)}, f, indent=2)
    except Exception:
        pass


# ============================================================================
# 3. Provider 发现
# ============================================================================

class ProviderManager:
    """动态发现并管理可用的AI提供商"""
    
    def __init__(self):
        self.providers = self._discover_providers()
        self.top20 = fetch_leaderboard_top20()
        
    def _discover_providers(self) -> List[Dict]:
        """自动发现配置了API_KEY的提供商"""
        providers = []
        env = dict(os.environ)
        
        for key, value in env.items():
            if not key.endswith("_API_KEY") or not value or len(value.strip()) < 10:
                continue
            
            prefix = key[:-8]  # 移除 _API_KEY 后缀
            name = prefix.replace("_", " ").title()
            
            # 特殊处理 BLTCY 代理
            if prefix == "BLTCY":
                base_url = env.get("BLTCY_PROXY_URL", "").rstrip("/")
                if not base_url:
                    continue
                providers.append({
                    "prefix": prefix,
                    "name": "BLTCY (Claude Proxy)",
                    "api_key": value.strip(),
                    "base_url": base_url,
                    "models": self._get_models(prefix, env),
                    "is_anthropic": True,  # 标记为 Anthropic 兼容
                })
                continue
            
            base_url = PROVIDER_BASE_URLS.get(prefix)
            if not base_url:
                continue
            
            providers.append({
                "prefix": prefix,
                "name": name,
                "api_key": value.strip(),
                "base_url": base_url,
                "models": self._get_models(prefix, env),
            })
        
        # 按优先级排序
        priority = {"DMXAPI": 1, "QINIU": 2, "XAI": 3, "OPENROUTER": 4, "ZEN": 5, "DEEPSEEK": 6}
        providers.sort(key=lambda p: priority.get(p["prefix"], 99))
        
        return providers
    
    def _get_models(self, prefix: str, env: Dict) -> List[str]:
        """获取提供商的模型列表"""
        model_list_str = env.get(f"{prefix}_MODEL_LIST", "").strip()
        if model_list_str:
            return [m.strip() for m in model_list_str.split(",") if m.strip()]
        return PROVIDER_DEFAULT_MODELS.get(prefix, [])
    
    def is_top20_match(self, model_id: str) -> bool:
        """检查模型是否在排行榜前20"""
        if not self.top20:
            return True  # 无排行榜数据时放行
        
        base = model_id.lower().replace("-free", "").replace("_free", "")
        core = base.split("/")[-1] if "/" in base else base
        core_nodot = core.replace("-", "").replace(".", "")
        
        for slug in self.top20:
            slug_nodot = slug.replace("-", "").replace(".", "")
            if slug_nodot in core_nodot or core_nodot in slug_nodot:
                return True
        return False
    
    def is_minimax_allowed(self, model_id: str) -> bool:
        """检查 MiniMax 模型是否在白名单"""
        mid = model_id.lower()
        if "minimax" not in mid:
            return True
        if any(b in mid for b in MINIMAX_BLOCKED):
            return False
        return any(a in mid for a in MINIMAX_ALLOWED)


# ============================================================================
# 4. API 调用
# ============================================================================

def call_api(provider: Dict, model: str, prompt: str) -> Optional[str]:
    """调用 AI API (支持 OpenAI 和 Anthropic 格式)"""
    try:
        import requests
        
        is_anthropic = provider.get("is_anthropic", False)
        base_url = provider["base_url"].rstrip("/")
        
        if is_anthropic:
            # Anthropic 兼容格式 (BLTCY)
            url = f"{base_url}/v1/messages"
            headers = {
                "Content-Type": "application/json",
                "x-api-key": provider["api_key"],
                "anthropic-version": "2023-06-01",
            }
            payload = {
                "model": model,
                "max_tokens": 8000,
                "messages": [{"role": "user", "content": prompt}],
            }
        else:
            # OpenAI 兼容格式
            if base_url.endswith("/v1"):
                url = f"{base_url}/chat/completions"
            else:
                url = f"{base_url}/v1/chat/completions"
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {provider['api_key']}",
            }
            
            # OpenRouter 特殊头
            if provider["prefix"] == "OPENROUTER":
                headers["HTTP-Referer"] = "https://github.com/Fatty911/lobe-chat"
                headers["X-Title"] = "LobeChat Upstream Sync"
            
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            }
        
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        
        if resp.status_code != 200:
            print(f"    ✗ HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        
        data = resp.json()
        
        if is_anthropic:
            return data.get("content", [{}])[0].get("text", "")
        else:
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
            
    except Exception as e:
        print(f"    ✗ 异常: {e}")
        return None


# ============================================================================
# 5. 冲突解决
# ============================================================================

def get_conflicted_files() -> List[str]:
    """获取有冲突的文件列表"""
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        capture_output=True, text=True
    )
    return [f for f in result.stdout.strip().split("\n") if f]


def resolve_file_conflict(file_path: str, provider_manager: ProviderManager) -> bool:
    """使用 AI 解决单个文件的冲突"""
    content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    
    if "<<<<<<<" not in content:
        print(f"  {file_path}: 无冲突标记，跳过")
        return True
    
    prompt = f"""You are an expert software engineer resolving git merge conflicts for a Lobe-Chat upstream sync.

Rules:
1. Fix ONLY conflict regions marked with <<<<<<<, =======, >>>>>>>
2. Keep all non-conflict code unchanged
3. Intelligently merge both versions, keeping the best parts
4. Preserve important features from both upstream and local changes
5. Maintain TypeScript/React best practices
6. Return ONLY the complete resolved file content, no markdown

File: {file_path}

Content with conflicts:
```
{content}
```"""
    
    for provider in provider_manager.providers:
        print(f"\n  尝试 Provider: {provider['name']}")
        
        for model in provider["models"][:3]:  # 每个Provider最多尝试3个模型
            # 检查模型是否在排行榜前20
            if not provider_manager.is_top20_match(model):
                print(f"    ⊘ {model}: 不在排行榜前20，跳过")
                continue
            
            # 检查 MiniMax 白名单
            if not provider_manager.is_minimax_allowed(model):
                print(f"    ⊘ {model}: MiniMax 模型不在白名单，跳过")
                continue
            
            print(f"    → 模型: {model}")
            
            result = call_api(provider, model, prompt)
            if result:
                # 清理可能的 markdown 标记
                cleaned = result.strip()
                if cleaned.startswith("```"):
                    cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
                    cleaned = re.sub(r"\n?```$", "", cleaned)
                
                # 验证是否还有冲突标记
                if "<<<<<<<" in cleaned or "=======" in cleaned or ">>>>>>>" in cleaned:
                    print(f"    ✗ 仍包含冲突标记")
                    continue
                
                Path(file_path).write_text(cleaned + "\n", encoding="utf-8")
                print(f"    ✓ 成功解决 {file_path}")
                return True
    
    return False


def main():
    print("=" * 60)
    print("Lobe-Chat 上游同步冲突解决 (Track 2)")
    print("=" * 60)
    
    # 初始化 Provider Manager
    manager = ProviderManager()
    
    if not manager.providers:
        print("❌ 未找到可用的 AI Provider，请配置 API Key")
        print("可配置的环境变量: DMXAPI_API_KEY, QINIU_API_KEY, XAI_API_KEY 等")
        sys.exit(1)
    
    print(f"\n发现 {len(manager.providers)} 个可用 Provider:")
    for p in manager.providers:
        print(f"  - {p['name']}: {len(p['models'])} 个模型")
    
    # 获取冲突文件
    conflicted = get_conflicted_files()
    
    if not conflicted:
        print("\n✅ 无冲突文件，同步成功")
        return
    
    print(f"\n发现 {len(conflicted)} 个冲突文件:")
    for f in conflicted:
        print(f"  - {f}")
    
    # 逐个解决冲突
    failed_files = []
    for file_path in conflicted:
        print(f"\n{'='*50}")
        print(f"解决: {file_path}")
        print("=" * 50)
        
        if not resolve_file_conflict(file_path, manager):
            failed_files.append(file_path)
            print(f"❌ 所有 Provider 均无法解决: {file_path}")
    
    if failed_files:
        print(f"\n⚠️ {len(failed_files)} 个文件未能解决:")
        for f in failed_files:
            print(f"  - {f}")
        print("\n请等待 Track 3 (OpenCode) 深度修复...")
        sys.exit(1)
    else:
        # 添加解决的文件
        for f in conflicted:
            subprocess.run(["git", "add", f], check=True)
        
        print("\n✅ 所有冲突已解决！")
        
        # 提交
        subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
        
        result = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", "🔀 chore: auto-resolve upstream merge conflicts with AI"], check=True)
            print("✓ 已提交修复")


if __name__ == "__main__":
    main()
