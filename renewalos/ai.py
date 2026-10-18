"""Optional real LLM adapter. Explicit structured output, minimized business signals."""
import json
import os
import urllib.request
from urllib.parse import urlparse
from .quality import canonical_signals, AdviceRejected

class AIUnavailable(Exception):
    pass

SYSTEM_PROMPT = """你是体育培训机构的内部客户服务辅助员。只准使用输入的匿名数值信号。
返回严格JSON对象，必须且仅有action_code/evidence_keys/message/uncertainty：
- action_code是以下其一：attendance_service_check, post_expiry_service,
  course_progress_review, routine_expiry_notice。
- 若attendance_drop为true则action_code必须为attendance_service_check，
  否则days_to_expiry<0必须为post_expiry_service，
  否则few_sessions为true必须为course_progress_review，
  其他情况为routine_expiry_notice。
- evidence_keys仅引用输入signals已有的字段：出勤下降必须含attendance_previous_28d和attendance_recent_28d；
  过期或常规到期提醒必须含days_to_expiry；低余课必须含remaining_sessions。
- message是内部员工行动建议，中文12~160字，不能包含家长身份或未经证实的流失原因；
  uncertainty是中文8~130字，明确仍需要人工确认。
禁止假设家庭经济、心理、疾病、价格阻力，禁止承诺优惠、自动群发或联络。
不输出代码块或对象外文本。"""


def suggest(signals: dict, course_type: str):
    base=os.getenv('RENEWAL_AI_BASE_URL','').strip().rstrip('/')
    key=os.getenv('RENEWAL_AI_API_KEY','').strip()
    model=os.getenv('RENEWAL_AI_MODEL','').strip()
    if not all((base,key,model)):
        raise AIUnavailable('未配置实际模型API，原规则建议仍可用，绝不伪装成AI。')
    parsed=urlparse(base)
    if parsed.scheme != 'https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1')):
        raise AIUnavailable('模型服务必须为HTTPS（仅本机可使用HTTP）。')
    if not parsed.netloc or parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise AIUnavailable('模型服务URL无效。')
    signals=canonical_signals(signals)
    if not isinstance(course_type,str):
        raise AIUnavailable('课程类型无效')
    # Course labels may be user-originated/imported content: do not send them to the model.
    body={'model':model,'messages':[{'role':'system','content':SYSTEM_PROMPT},
        {'role':'user','content':json.dumps({'course_category':'体育培训','signals':signals},ensure_ascii=False)}],
        'temperature':0.1,'max_tokens':350}
    req=urllib.request.Request(base+'/chat/completions',data=json.dumps(body,ensure_ascii=False).encode('utf-8'),
         headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    try:
        # An invalid response is a rejected proposal, not a reason to display raw model text.
        with urllib.request.urlopen(req,timeout=12) as response:
            if int(response.headers.get('Content-Length','0'))>20000:
                raise AIUnavailable('模型响应超过上限')
            raw=response.read(20001)
        if len(raw)>20000: raise AIUnavailable('模型响应超过上限')
        data=json.loads(raw)
        content=data['choices'][0]['message']['content']
        if not isinstance(content,str): raise AIUnavailable('模型没有返回结构化文本')
        proposal=json.loads(content)
        if not isinstance(proposal,dict): raise AIUnavailable('模型没有返回JSON对象')
        return proposal,model
    except AIUnavailable: raise
    except (ValueError,KeyError,IndexError,TypeError) as exc:
        raise AIUnavailable('模型返回了无效的结构化数据，已拒绝展示。') from exc
    except Exception as exc:
        raise AIUnavailable('模型请求失败，保持规则模式。') from exc