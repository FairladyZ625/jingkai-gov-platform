"""依赖未接入时的确定性 provider，签名对应知识库问答、模型与工具桥。"""

import re


class MockSkillProvider:
    def search(self, user, params):
        return {"hits": [], "total": 0, "terms": [], "facets": {}}

    def ask(self, user, params):
        return {"answer": "未找到可以引用的知识库片段。", "confidence": "none", "citations": []}

    def draft(self, user, prompt, text, knowledge):
        name = re.sub(r"^(?:帮我|请)?(?:做|创建|制作)(?:一个|个)?技能[：:，,\s]*", "", text)
        name = name.strip("。！?？ ")[:24] or "知识整理助手"
        format_name = "要点"
        for keyword, output in (("表格", "表格"), ("清单", "清单"), ("公文", "公文")):
            if keyword in text:
                format_name = output
                break
        return {
            "name": name,
            "summary": text,
            "spec": {
                "triggers": [name],
                "inputs": [{"key": "materials", "label": "已有材料", "type": "textarea", "required": True}],
                "steps": [{"type": "kb", "query": name}, {"type": "model"}],
                "output": {"title": name, "format": format_name},
                "prompt": f"{text}\n已有材料：{{{{materials}}}}\n请写结论与出处，缺项标为待确认。",
            },
            "questions": ["可以提供哪些输入材料？", "结果要依据哪个知识库？"],
        }

    def generate(self, user, model, request):
        # 样例 provider 只展示收到的材料，不编造业务判断或知识库依据。
        details = [f"- {field}：{value}" for field, value in request["inputs"].items()]
        markdown = "\n".join(details) if details else "缺少可用于形成结论的输入。"
        return {"model": model, "markdown": markdown}

    def tool(self, user, name, args, idempotency_key):
        return {"note": f"{name} 尚未接入业务工具桥，未执行实际业务操作。"}
