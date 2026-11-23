#!/usr/bin/env python3
"""对单个真实 provider 发送一次固定公开文本，输出状态及文本长度。"""

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "core/server"), str(ROOT / "core/sdk")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", help="配置中的模型标识。Codex CLI 仅接受显式 --provider codex-cli。"
                        "默认按 JKQ_MODEL_PROVIDER 和配置顺序选择 HTTP 服务。")
    args = parser.parse_args()
    codex_requested = args.provider == "codex-cli"
    provider_id = args.provider or os.getenv("JKQ_MODEL_PROVIDER", "").strip()
    if codex_requested:
        import shutil

        if shutil.which("codex") is None:
            print("跳过：本机没有 codex CLI。")
            return 0
    else:
        # CI 只运行 mock；真实调用需要单独运行此入口并显式注入部署配置。
        if not any(name.startswith("JKQ_") and name.endswith("_BASE_URL") for name in os.environ):
            print("跳过：未配置模型服务地址。")
            return 0

    import anyio

    from haiknow_core.aihub.errors import AIError
    from haiknow_core.aihub.providers.jkq_chat import (
        SMOKE_PROMPT, ProviderRejected, codex_smoke, load_config, openai_chat, provider_from_environment,
    )

    try:
        if codex_requested:
            content = codex_smoke(os.getenv("JKQ_CODEX_MODEL_NAME", "").strip() or None)
        else:
            config = load_config()
            http_models = [item for item in config.models if item.kind in ("openai", "deepseek")]
            if args.provider:
                candidates = [item for item in http_models if item.id == args.provider]
                if not candidates:
                    parser.error("请选择已登记的 OpenAI 兼容 provider 或 codex-cli。")
            else:
                candidates = sorted(
                    (item for item in http_models if item.enabled),
                    key=lambda item: item.id != provider_id,
                )
            invalid = False
            for definition in candidates:
                try:
                    provider = provider_from_environment(definition)
                except ValueError:
                    if args.provider:
                        raise
                    invalid = True
                    continue
                if provider is not None:
                    provider_id = definition.id
                    break
            else:
                if invalid:
                    raise ValueError("模型接入地址无效。")
                print("跳过：所选 provider 的地址、模型名或必需密钥未配置。")
                return 0
            payload = {"messages": [{"role": "user", "content": SMOKE_PROMPT}]}
            content, _ = anyio.run(
                openai_chat, provider["base_url"], provider["api_key"], provider["model"], payload, 30,
            )
    except (AIError, ProviderRejected, ValueError) as error:
        kind = error.kind if isinstance(error, AIError) else (
            "provider_error" if isinstance(error, ProviderRejected) else "invalid_config"
        )
        print(f"模型冒烟失败（{kind}）。", file=sys.stderr)
        return 1

    print(f"{provider_id} 模型冒烟通过，返回非空文本（{len(content.strip())} 字符）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
