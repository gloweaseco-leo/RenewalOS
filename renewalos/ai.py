"""Optional real OpenAI-compatible LLM adapter. Never sends learner identifiers."""
import json
import os
import urllib.request
from urllib.parse import urlparse

class AIUnavailable(Exception): pass

def suggest(signals:dict, course_type:str):
    base=os.getenv("RENEWAL_AI_BASE_URL","").strip().rstrip("/")
    key=os.getenv("RENEWAL_AI_API_KEY","").strip()
    model=os.getenv("RENEWAL_AI_MODEL","").strip()
    if not all((base,key,model)):
        raise AIUnavailable("未配置实际模型API，已保留规则建议；不会伪装成AI回答。")
    parsed=urlparse(base)
    if parsed.scheme!="https" and not (parsed.hostname in ("localhost","127.0.0.1") and parsed.scheme=="http"):
        raise AIUnavailable("模型服务必须使用HTTPS（仅本机地址可用HTTP）。")
    if not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise AIUnavailable("模型服务URL不合法。")
    prompt=("你是体育培训机构的客户服务辅助员。只能依据提供的非识别化事实给出一段不超过120字的建议。"
            "禁止捏造缺课原因、健康情况、家庭经济信息或客户意愿；先服务后营销；不得承诺折扣或自动联系客户。"
            "若证据不足必须说需要人工确认。")
    body={"model":model,"messages":[{"role":"system","content":prompt},
           {"role":"user","content":json.dumps({"course_type":course_type,"signals":signals},ensure_ascii=False)}],
          "temperature":0.2,"max_tokens":220}
    req=urllib.request.Request(base+"/chat/completions",data=json.dumps(body).encode("utf-8"),
                headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=12) as r:
            content=json.load(r)
        advice=content["choices"][0]["message"]["content"]
        if not isinstance(advice,str) or not advice.strip() or len(advice)>1500:
            raise AIUnavailable("模型输出无效，建议保持规则模式。")
        return advice.strip(),model
    except AIUnavailable: raise
    except Exception as e:
        raise AIUnavailable("模型调用失败，原规则建议未受影响。") from e