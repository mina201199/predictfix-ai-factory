"""Natural-language database queries compile to parameterized read-only SQL templates."""
import re
import joblib
from pathlib import Path
ROUTER_DIR=Path(__file__).resolve().parents[1]/'artifacts'
import json,hashlib
ROUTER_REPORT=json.loads((ROUTER_DIR/'chat-router-report.json').read_text(encoding='utf-8')) if (ROUTER_DIR/'chat-router-report.json').exists() else {}
ROUTER_EVAL=json.loads((ROUTER_DIR/'chat-router-api-evaluation.json').read_text(encoding='utf-8')) if (ROUTER_DIR/'chat-router-api-evaluation.json').exists() else {}
ROUTER_CANDIDATE=ROUTER_DIR/'chat-router-v2.joblib'
ROUTER_READY=ROUTER_CANDIDATE.exists() and ROUTER_EVAL.get('promotable',False) and ROUTER_EVAL.get('model_sha256')==hashlib.sha256(ROUTER_CANDIDATE.read_bytes()).hexdigest()
INTENT_MODEL=joblib.load(ROUTER_CANDIDATE if ROUTER_READY else ROUTER_DIR/'intent-model.joblib')
ROUTER_NAME='zh-maintenance-router-v2' if ROUTER_READY else 'zh-maintenance-intent-v1'
ROUTER_THRESHOLD=ROUTER_REPORT.get('abstention_threshold',0.9)
def classify(q):
    scores=INTENT_MODEL.predict_proba([q])[0];i=int(scores.argmax());return str(INTENT_MODEL.classes_[i]),round(float(scores[i]),4)
from sqlalchemy import text
from . import store
from .operations import people
from .copilot import analyze
from .knowledge import retrieve, DOCUMENTS
from pydantic import BaseModel,Field

class ChatInput(BaseModel):
    text:str=Field(min_length=1,max_length=2000)
    history:list[dict]=Field(default_factory=list,max_length=8)

def unknown(message='我不知道：目前資料庫與知識庫沒有足夠資料回答這個問題。請補充設備編號、完整問題或相關文件。',clarification=False):
    return {'answer':message,'route':'clarification' if clarification else 'unknown','llm_used':False,'sql':None,'rows':[],'machine_ids':[],'needs_confirmation':clarification,'answer_method':'insufficient_evidence'}

def health_condition(question):
    """Only compile understood comparisons; never silently discard a condition."""
    normalized=question.translate(str.maketrans('０１２３４５６７８９％＜＞＝','0123456789%<>='))
    matches=list(re.finditer(r'(不超過|不高於|不大於|至多|最多|不低於|不少於|至少|低於|小於|不到|高於|大於|超過|等於|<=|>=|<|>|=)\s*(\d+(?:\.\d+)?)\s*%?',normalized))
    operators={'不超過':'<=','不高於':'<=','不大於':'<=','至多':'<=','最多':'<=','不低於':'>=','不少於':'>=','至少':'>=','低於':'<','小於':'<','不到':'<','高於':'>','大於':'>','超過':'>','等於':'='}
    if not matches:
        if re.search(r'%|低於|小於|高於|大於|超過|介於|之間|不超過|不低於|[<>]',normalized):
            return unknown('我不確定你要查的健康度條件。請說明比較方式與數值，例如「設備健康度低於 30%」。',True)
        return None
    if len(matches)!=1 or re.search(r'介於|之間|或者|或是|以及|而且|同時|但|又|且|或|以上|以下',normalized):
        return unknown('我還無法完整理解這個組合條件，不能只套用其中一部分。請拆成單一查詢，例如「設備健康度低於 30%」。',True)
    value=float(matches[0][2])
    if not 0<=value<=100:return unknown('健康度查詢數值須介於 0% 到 100%。請確認你要查的門檻。',True)
    return operators.get(matches[0][1],matches[0][1]),value

def question_guard(question):
    if re.search(r'今天|昨天|明天|本週|上週|上周|本月|這個月|最近|今年',question) and re.search(r'工單|任務|維修|保養|健康',question):
        return unknown('資訊不足：目前對話查詢尚未支援這個日期或歷史條件，不能拿全部資料當作該期間的結果。請透過工單頁確認日期，或提供要比較的紀錄。')
    if re.search(r'超過.*(預計|估計)|逾期|到期|適合|可以接|有庫存|倉庫|備品.*(多少|有哪些)',question):
        return unknown('資訊不足：目前對話查詢沒有完整的到期、庫存或可派工判斷依據，不能用其他資料代替答案。請到對應作業頁確認，或補充紀錄。')
    if re.search(r'這台|那台|它的|那個|這個零件',question) and not re.search(r'CNC[- ]?\d+',question,re.I):
        return unknown('我不確定你指的是哪台設備或哪個零件。請提供設備編號與零件名稱。',True)
    if re.search(r'比.*(昨天|上週|上周|之前)|趨勢|變差|改善了|健康.*(上週|上周|昨天)',question):
        return unknown('資訊不足：目前沒有可比較的歷史健康度量測，無法判斷是否變差。請提供兩個時間點的量測紀錄。')
    if re.search(r'還能撐|撐多久|多久會壞|剩餘壽命|還能用多久|復機|直接量產|先停機|要停機',question):
        return unknown('資訊不足：我不知道這台設備是否需要停機、可以復機或還能使用多久。需要對應機型的手冊、現場量測與檢查結果，由負責人確認。')
    if re.search(r'(有哪些|哪些|幾台|幾張|多少|查|列出)',question) and re.search(r'且|同時|但是|但|而且|以及|或者',question):
        return unknown('我還無法完整理解這個組合查詢，請把條件分開詢問；我不會忽略其中一個條件後列出結果。',True)
    if len(set(re.findall(r'CNC[- ]?\d+',question,re.I)))>1:
        return unknown('我不確定你要比較哪些項目。請先指定一台設備及要查的資訊。',True)
    return None

def verified_document_answer(result,question=''):
    """Fail closed: a citation alone does not substantiate generated claims."""
    answer=str(result.get('answer','')).strip()
    citations=result.get('citations') or []
    if result.get('needs_confirmation') or not citations or len(answer)<35:return False
    source=' '.join(str(c.get('text','')) for c in citations)
    for topic in ['刀具','換刀','冷卻','異音','主軸','軸承','潤滑','尺寸','定位','螺桿','漏油','漏液','交班','結案','驗收','振動']:
        if topic in question and topic not in answer:return False
    claims=re.split(r'[。！？\n]+',answer)
    # 要求與原文完整一句相同：只比對子字串會放行截掉「不」「未」或前半子句、語意相反的片段
    sentences={s.strip() for c in citations for s in re.split(r'[。！？\n]+',str(c.get('text','')))}
    for claim in claims:
        claim=claim.strip()
        if not claim:continue
        if any(claim==str(c.get('title','')) or claim==str(c.get('id','')) for c in citations):continue
        if claim not in sentences:return False
    return bool(source and answer)

def shift_answer(question):
    roster=people();shifts={p['shift'] for p in roster}
    if not any(w in question for w in ['班別','早班','中班','晚班','夜班','白班','白斑','排班','當班','輪班']):return None
    if any(w in question for w in ['今天','明天','現在','目前當班','此刻','本週','下週','昨日','昨天']):
        return unknown('我不知道實際當班名單：目前只有 DEMO 班別，沒有日期排班表或出勤資料。')
    if any(w in question for w in ['白班','白斑','夜班']) and not any(w in question for w in shifts):
        return unknown('我不知道你指的白班／夜班名單：目前資料只分早班、中班、晚班，尚未定義白班或夜班的對應。請確認要查哪一班。',True)
    selected=next((shift for shift in sorted(shifts) if shift in question),None)
    rows=[{'engineer':p['name'],'shift':p['shift'],'source':'demo_roster'} for p in roster if selected is None or p['shift']==selected]
    return {'answer':('DEMO '+selected+'人員：' if selected else 'DEMO 人員班別：')+'\n'+'\n'.join(r['engineer']+' · '+r['shift'] for r in rows)+'\n這是展示班別，不是實際日期排班或出勤紀錄。','route':'database','query_kind':'shifts','rows':rows,'sql':None,'machine_ids':[],'llm_used':False,'method':'explicit_shift_filter','source':'demo_roster'}

def person_tasks_answer(question):
    if not re.search(r'幾台|幾張|幾筆|多少|有哪些|哪幾台|負荷|任務|工單|要修|維修',question):return None
    candidates=[p for p in people() if any(re.search(r'(?<![A-Za-z])'+re.escape(alias)+r'(?![A-Za-z])',question,re.I) for alias in [p['name'],p['name'].split()[0]])]
    if not candidates:return None
    if len(candidates)!=1:return unknown('你提到了多位人員，請先指定一位要查的維修人員。',True)
    if re.search(r'已完成|已結案|待審核|待主管審核',question):return unknown('目前這個人員查詢支援未結案任務，請到工單頁依負責人及狀態查看其他案件。')
    if re.search(r'怎麼|如何|步驟|原因|歷史|曾經|以前',question):return None
    person=candidates[0]
    with store.Session() as session:
        tasks=[dict(r) for r in session.execute(text("SELECT id,machine,issue,status FROM tickets WHERE engineer=:engineer AND status != '已完成' ORDER BY created_at DESC"),{'engineer':person['name']}).mappings()]
    ids=list(dict.fromkeys(t['machine'] for t in tasks))
    answer=f"{person['name']} 目前有 {len(ids)} 台設備、{len(tasks)} 筆未結案工單。"
    if tasks:answer+='\n'+'\n'.join(f"{t['machine']} · {t['issue']} · {t['status']}" for t in tasks)
    else:answer+='\n目前沒有已指派給此人的未結案工單。'
    demos=person.get('demo_tasks',[])
    if demos:answer+='\n履歷中的展示任務（不計入正式工單）：\n'+'\n'.join(demos)
    return {'answer':answer,'route':'database','query_kind':'person_tasks','rows':tasks,'machine_ids':ids,'llm_used':False,'parameters':{'engineer':person['name']},'machine_count':len(ids),'ticket_count':len(tasks),'method':'named_person_database_query'}

def procedure_answer(question):
    """Answer supported general procedures from complete authored sections."""
    if re.search(r'車床|車削|削車床',question) and re.search(r'怎麼修|如何修|怎麼維修',question):
        return unknown('你指的是車削車床的維修嗎？請補充設備編號及症狀，例如主軸異音、刀片磨耗、尺寸偏差或液壓異常。不同症狀的排查方式不同，我可以查對應檢查流程，不能直接判定要更換哪個零件。',True)
    # Concrete specifications and authorization questions must not become generic guides.
    if re.search(r'幾年|幾度|多少|扭力|扭矩|料號|容差|合格門檻|安全門檻|壽命|正常溫度|為什麼|原因',question):return None
    action=bool(re.search(r'怎麼|如何|檢查|驗收|查核|記錄|紀錄|流程|步驟|確認|首件|試切',question))
    routes=[(r'換刀|刀具更換|首件','GUIDE-DEMO-03'),(r'主軸.*(異音|振動)|異音.*主軸','GUIDE-DEMO-01'),(r'冷卻','GUIDE-DEMO-02'),(r'螺桿|定位','GUIDE-DEMO-04'),(r'交班|交接|派工','GUIDE-DEMO-05'),(r'結案','GUIDE-DEMO-06'),(r'漏油|漏液','GUIDE-DEMO-08')]
    selected=next((docid for pattern,docid in routes if action and re.search(pattern,question)),None)
    learned=False
    if selected is None:
        predicted,confidence=classify(question)
        # Learned synonyms select an existing source, never invent a procedure.
        topics={'GUIDE-DEMO-01':r'主軸|軸承','GUIDE-DEMO-02':r'冷卻|循環泵','GUIDE-DEMO-03':r'換刀|刀|首件|試切','GUIDE-DEMO-04':r'螺桿|定位|进给','GUIDE-DEMO-05':r'交班|交接|派工|移交','GUIDE-DEMO-06':r'工單|維修單|修好|報告','GUIDE-DEMO-08':r'漏油|漏液|油液|洩漏'}
        if predicted in topics and confidence>=ROUTER_THRESHOLD and re.search(topics[predicted],question):selected=predicted;learned=True
    if selected is None:return None
    doc=next((d for d in DOCUMENTS if d['id']==selected),None)
    if doc is None:return None
    return {'answer':f"依示範作業流程《{doc['title']}》：\n{doc['text']}\n來源：{doc['id']} · {doc['section']}。這是通用示範流程，具體規格須查適用機型的手冊。",'route':'documents','citations':[doc],'machine_ids':[],'llm_used':False,'needs_confirmation':False,'answer_method':'verified_authored_procedure','router_method':'trained_classifier_with_topic_guard' if learned else 'explicit_procedure_match','router_model':ROUTER_NAME,'source_notice':'原創示範流程，非原廠手冊或復機授權。'}

def database_answer(question):
    mid=re.search(r'CNC[- ]?(\d{1,4})',question,re.I)
    machine='CNC-'+mid.group(1).zfill(2) if mid else None
    params={}
    intent,score=classify(question)
    explicit_idle=any(w in question for w in ["誰沒有","誰沒","哪些人沒","沒有工單的人","誰空閒","誰有空","沒任務"])
    # A closed-set model always chooses a class, even for unrelated questions.
    # Only accept its suggestion when the question also has matching semantic evidence.
    anchors={
        'idle_people':r'(誰|哪些|哪位|技師|工程師|人員|同仁).*(沒|無|空閒|有空|空檔)|零工單|沒有.*(工單|任務|工作|案子)|尚未接|還沒被派',
        'review':r'審核|批准|核准|待審|已提交|主管.*確認',
        'unassigned':r'未派|未指派|待指派|沒派|沒指定|沒分配|沒分派|待分派|沒指定|還沒有工程師|沒安排|尚未安排|沒人處理|誰都還沒接|還沒指定',
        'open_tickets':r'工單|工作單|任務|未結案|未完成|還在修|維修中|案件',
        'history':r'歷史|紀錄|記錄|維修過|報修|過去|以前|曾經|歷年',
        'workload':r'負荷|負載|最忙|忙碌|工作量|任務.*(數|量|最多)|工單.*(數|量|最多)|案件最多',
    }
    task_context=bool(re.search(r'工單|工作單|任務|案件|維修|報修|派工|張單|單子',question))
    person_context=bool(re.search(r'誰|人員|技師|工程師|師傅|哪位|同仁|各人',question))
    supported=intent in anchors and bool(re.search(anchors[intent],question))
    if intent=='idle_people':supported=supported and person_context and (task_context or bool(re.search(r'空閒|有空[？?！!，。\s]*$|空檔|沒工作|零工單|沒案子',question)))
    elif intent=='workload':supported=supported and person_context
    else:supported=supported and task_context
    special=intent if score>=.30 and supported else None
    if re.search(r'是什麼|是啥|意思|定義|怎麼使用',question) and not re.search(r'白班|白斑|夜班',question):return None
    shift=shift_answer(question)
    if shift is not None:return shift
    person=person_tasks_answer(question)
    if person is not None:return person
    if any(w in question for w in ['刪除資料表','DROP ','DELETE ','UPDATE ','INSERT ','刪除全部']):
        return {'answer':'對話查詢只讀取資料。請使用機台或工單頁的操作功能。','route':'database','sql':None,'rows':[],'llm_used':False}
    if explicit_idle and any(w in question for w in ['工單','工作','任務','案子','空閒','有空']) or special=='idle_people':
        roster=' UNION ALL '.join(('SELECT :p0 AS name' if i==0 else f'SELECT :p{i}') for i in range(len(people())))
        params={f'p{i}':p['name'] for i,p in enumerate(people())}
        sql="SELECT p.name AS engineer,COUNT(t.id) AS open_tasks FROM ("+roster+") p LEFT JOIN tickets t ON t.engineer=p.name AND t.status != '已完成' GROUP BY p.name HAVING COUNT(t.id)=0 ORDER BY p.name LIMIT 50";route='idle_people'
    elif special=='review' or any(w in question for w in ['待審核','待主管審核','主管審核','等主管']):
        sql="SELECT id,machine,issue,engineer,status,created_at FROM tickets WHERE status='待主管審核' ORDER BY created_at LIMIT 50";route='tickets'
    elif (machine or any(w in question for w in ['機台','機器','設備','哪台','幾台'])) and any(w in question for w in ['檢查','檢修','保養','維修','異常','警示','注意','風險','危險','健康','有哪些','幾台']) and not any(w in question for w in ['工單','維修紀錄','任務','報修']):
        if re.search(r'溫度|振動|使用率|電流|軸承|刀具|刀片|冷卻泵|螺桿|零件|哪裡|原因|怎麼|如何處理|怎麼處理',question):
            return unknown('資訊不足：這個查詢不能用設備最低健康度代替你指定的零件、量測或原因。請提供設備編號與要查的項目；目前對話查詢僅支援設備最低零件健康度。')
        condition=health_condition(question)
        if isinstance(condition,dict):return condition
        sql="SELECT id, json_extract(payload, '$.name') AS name, json_extract(payload,'$.util') AS utilization, (SELECT min(json_extract(value,'$[1]')) FROM json_each(json_extract(payload,'$.parts'))) AS health FROM machines WHERE active=1"
        if machine:sql+=' AND id=:machine';params['machine']=machine
        if condition:
            op,value=condition
            sql+=f" AND (SELECT min(json_extract(value,'$[1]')) FROM json_each(json_extract(payload,'$.parts'))) {op} :health_threshold"
            params['health_threshold']=value
        elif not machine and any(w in question for w in ['檢查','檢修','保養','維修','異常','警示','注意','風險','危險']):sql+=' AND (SELECT min(json_extract(value,\'$[1]\')) FROM json_each(json_extract(payload,\'$.parts\'))) < 70'
        sql+=' ORDER BY health IS NULL, health ASC LIMIT 50'
        route='machines'
    elif special in ['unassigned','open_tickets','history'] or any(w in question for w in ['工單','維修紀錄','維修過','報修','任務','派工']) and not any(w in question for w in ['負荷','最忙','最多任務','任務最多']):
        if re.search(r'怎麼|如何|要附|需要|步驟|流程|哪裡|原因',question):return None
        sql='SELECT id,machine,issue,engineer,status,created_at FROM tickets WHERE 1=1'
        if machine:sql+=' AND machine=:machine';params['machine']=machine
        name=next((p['name'] for p in people() if p['name'].lower() in question.lower()),None)
        if name:sql+=' AND engineer=:engineer';params['engineer']=name
        if '已完成' not in question and (special in ['unassigned','open_tickets'] or any(w in question for w in ['未完成','未結案','待處理','任務','未派工'])):sql+=" AND status != '已完成'"
        if special=='unassigned' or any(w in question for w in ['未派工','未指派','沒派','沒指定']):sql+=" AND engineer = '待指派'"
        if '已完成' in question and '未完成' not in question and '未結案' not in question:sql+=" AND status = '已完成'"
        sql+=' ORDER BY created_at DESC LIMIT 50';route='tickets'
    elif special=='workload' or any(w in question for w in ['誰','人員','技師','工程師']) and any(w in question for w in ['負荷','忙','任務','空閒','工作量','最多']):
        sql="SELECT engineer,COUNT(*) AS open_tasks FROM tickets WHERE status != '已完成' GROUP BY engineer ORDER BY open_tasks DESC LIMIT 50";route='workload'
    else:return None
    if store.engine.dialect.name!='sqlite':return {'answer':'此自然語言查詢原型目前使用 SQLite，PostgreSQL 查詢模板尚未適配。','route':'database','llm_used':False,'rows':[],'sql':None}
    with store.Session() as s:rows=[dict(r) for r in s.execute(text(sql),params).mappings().all()]
    if route=='machines':
        if machine and not rows:return unknown('資訊不足：找不到這台啟用設備或它沒有符合指定條件。請確認設備編號及查詢條件。')
        answer=('依目前設備資料，'+str(len(rows))+' 台符合條件：\n'+'\n'.join(f"{r['id']} · {r['name']} · "+('健康度未知' if r['health'] is None else f"{'警示' if r['health']<45 else '注意' if r['health']<70 else '正常'} · 健康 {r['health']}%") for r in rows)) if rows else '目前沒有符合條件的設備。'
        answer+='\n零件健康為 DEMO 設定，僅用來示範巡檢排序。'
        answer+='\n查詢欄位：設備所有已知零件健康度的最低值；不是故障機率。'
    elif route=='idle_people':answer=('目前沒有未結案工單的人員（'+str(len(rows))+' 位）：\n'+'\n'.join(r['engineer'] for r in rows)+'\n無工單不等於當班可用，派工前仍需確認班別。') if rows else '所有人員目前都有未結案工單。'
    elif route=='tickets':answer=('找到 '+str(len(rows))+' 筆工單：\n'+'\n'.join(f"{r['machine']} · {r['issue']} · {r['engineer']} · {r['status']}" for r in rows)) if rows else '目前沒有符合條件的工單。'
    else:answer=('未結案任務：\n'+'\n'.join(f"{r['engineer']}：{r['open_tasks']} 筆" for r in rows)) if rows else '目前沒有未結案任務。'
    return {'answer':answer,'route':'database','query_kind':route,'sql':sql,'parameters':params,'rows':rows,'llm_used':False,'method':'intent_classifier_and_rules_to_parameterized_sql','intent_model':ROUTER_NAME,'intent':intent,'intent_score':score,'machine_ids':list(dict.fromkeys(r.get('machine',r.get('id')) for r in rows if str(r.get('machine',r.get('id',''))).startswith('CNC-'))),'limit':50}

def register(app):
    @app.post('/api/chat')
    async def chat(body:ChatInput):
        q=body.text.strip()
        if any(w in q for w in ['這台','那台','它的']) and not re.search(r'CNC',q,re.I):
            context=next((str(h.get('content','')) for h in reversed(body.history) if h.get('role')=='user'),None)
            if context:
                ids=set(re.findall(r'CNC[- ]?\d+',context,re.I))
                if len(ids)==1:q+=' '+next(iter(ids))
        guard=question_guard(q)
        if guard is not None:return guard
        if any(w in q for w in ['薪水','薪資','薪酬','時薪','手機號','電話號','證照號','生日','住址','年薪']):return unknown('我不知道：目前沒有保存這項人員資料，不能推測或編造。')
        codes=re.findall(r'\bE\d{3}\b',q,re.I)
        if any(code.upper()!='E102' for code in codes):return unknown('我不知道這個警報碼的意思：目前只收錄 DEMO E102。請提供廠牌、控制器、機型與完整警報文字或手冊。')
        procedure=procedure_answer(q)
        if procedure is not None:return procedure
        result=database_answer(q)
        if result is not None:return result
        if any(w in q for w in ['可以問','能做什麼','怎麼使用','功能']):return {'answer':'我可以查：需要檢查的機台、設備健康、未結案工單、某機台維修紀錄、人員任務負荷、早班／中班／晚班 DEMO 名單；也能查文件：換刀、冷卻、異音、尺寸誤差、交班與結案流程。資料庫查詢是唯讀，派工與結案請用操作按鈕。','route':'help','llm_used':False}
        topics=['刀具','換刀','冷卻','異音','主軸','軸承','潤滑','尺寸','定位','螺桿','漏油','漏液','交班','交接','結案','驗收','派工','工單','健康度','使用率','MTBF','E102','振動','振动','檢核','復測']
        evidence=retrieve(q)
        if not any(topic.lower() in q.lower() for topic in topics) or not evidence or evidence[0]['score']<.12:
            return unknown()
        if any(w in q for w in ['薪水','薪資','電話','證照','生日','住址','老闆','天氣','休假']):return unknown()
        if any(w in q for w in ['幾年','正常溫度','正常電流','正常振動','合格門檻','安全門檻']):return unknown('我不知道這台設備的原廠數值規格或壽命：目前沒有對應機型的手冊與驗證資料。請提供廠牌、型號及量測條件。')
        if any(w in q for w in ['保證','一定','剩餘壽命','還能用多久','會不會故障','能不能復機','可以復機','能否復機']):
            return unknown('我不知道這台設備是否可以復機或還能使用多久：目前沒有足夠的實機量測與驗收依據，不能替主管核准。')
        history=[{'role':h.get('role'),'content':str(h.get('content',''))[:180]} for h in body.history[-2:] if h.get('role') in ['user','assistant']]
        result=await analyze(q,history)
        result['route']='documents'
        if re.search(r'不知道|不確定|無法確認|沒有.{0,8}(依據|資料)|證據不足|資料不足',result['answer']):
            result['route']='unknown';result['machine_ids']=[];result['answer_method']='insufficient_evidence';return result
        if not verified_document_answer(result,q):
            return unknown('資訊不足：我找到可能相關的文件，但無法確認內容足以回答你的問題，因此不提供推測答案。請補充設備型號、症狀與適用手冊。')
        result['machine_ids']=[]
        return result
