"""只供验收：真实 SkillProvider/JobService/模型网关，最终 HTTP 协议由内存桩应答。"""
import json
from copy import copy
from pathlib import Path

import httpx

ENDPOINT = "https://skills-fixture.invalid/v1"
MODEL = "ci-skills-protocol"


def reply(request):
    assert str(request.url) == ENDPOINT + "/chat/completions"
    envelope = json.loads(request.content)
    assert envelope["model"] == MODEL
    data = json.loads(envelope["messages"][-1]["content"])
    if "passages" in data:
        excerpts = [dict(passage=p["passage"], quote=p["sentences"][0])
                    for p in data["passages"][:1] if p["sentences"]]
        content = json.dumps(excerpts, ensure_ascii=False)
    elif "knowledge" in data and "text" in data:
        text = data["text"]
        content = json.dumps(dict(name="协议夹具：" + text[:24], summary="按输入查阅公开依据", questions=[],
                                  spec=dict(inputs=[dict(key="topic", label="主题", type="text", required=True,
                                                         sample=text)], triggers=[text],
                                            steps=[dict(type="kb", query="{{topic}}", space="policy"),
                                                   dict(type="model")],
                                            output=dict(title="核对结果", format="清单"), prompt="{{topic}}")),
                             ensure_ascii=False)
    else:
        assert "prior" in data and "inputs" in data and "title" in data
        hits = [h for step in data["prior"] for h in step["result"].get("hits", [])]
        content = "【CI 内存协议桩】" + data["title"] + "\n" + (hits[0]["snippet"] if hits else "依据待确认")
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def install(app, monkeypatch, *, approved=True):
    from haiknow_core.aihub.providers.jkq_chat import load_config, provider_from_environment
    from jkq.models import ModelService

    service = app.state.jkq_models
    original = service.call
    scoped = copy(service)
    definition = service.models["local"]
    with monkeypatch.context() as env:
        env.setenv(definition.env + "_BASE_URL", ENDPOINT)
        env.setenv(definition.env + "_CONFIDENTIAL_BASE_URL", ENDPOINT if approved else "")
        env.setenv(definition.env + "_NAME", MODEL)
        config = load_config(Path(app.state.platform.config_dir) / "models.yaml")
        local = provider_from_environment(definition, "local" in config.confidential_providers)
    assert local and local["allow_outbound"] == ("confidential" if approved else "internal")
    scoped.providers = dict.fromkeys(service.providers)
    scoped.providers["local"] = local
    scoped.primary = "local"
    scoped.transport = httpx.MockTransport(reply)

    def dispatch(user, payload, **kwargs):
        if kwargs.get("app_id") == "skills":
            return ModelService.call(scoped, user, payload, **kwargs)
        return original(user, payload, **kwargs)
    service.call = dispatch
