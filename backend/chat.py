"""Natural-language database queries compile to parameterized read-only SQL templates."""
import re
import joblib
from pathlib import Path
INTENT_MODEL=joblib.load(Path(__file__).resolve().parents[1]/"artifacts/intent-model.joblib")
def classify(q):
    scores=INTENT_MODEL.predict_proba([q])[0];i=int(scores.argmax());return str(INTENT_MODEL.classes_[i]),round(float(scores[i]),4)
from sqlalchemy import text
from . import store
from .operations import people
from .copilot import analyze
from .knowledge import retrieve
from pydantic import BaseModel,Field

class ChatInput(BaseModel):
    text:str=Field(min_length=1,max_length=2000)
    history:list[dict]=Field(default_factory=list,max_length=8)

def unknown(message='我不知道：目前資料庫與知識庫沒有足夠資料回答這個問題。請補充設備編號、完整問題或相關文件。',clarification=False):
    return {'answer':message,'route':'clarification' if clarification else 'unknown','llm_used':False,'sql':None,'rows':[],'machine_ids':[],'needs_confirmation':clarification,'answer_method':'insufficient_evidence'}

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
    if any(w in question for w in ['刪除資料表','DROP ','DELETE ','UPDATE ','INSERT ','刪除全部']):
        return {'answer':'對話查詢只讀取資料。請使用機台或工單頁的操作功能。','route':'database','sql':None,'rows':[],'llm_used':False}
    if explicit_idle and any(w in question for w in ['工單','工作','任務','案子','空閒','有空']) or special=='idle_people':
        roster=' UNION ALL '.join(('SELECT :p0 AS name' if i==0 else f'SELECT :p{i}') for i in range(len(people())))
        params={f'p{i}':p['name'] for i,p in enumerate(people())}
        sql="SELECT p.name AS engineer,COUNT(t.id) AS open_tasks FROM ("+roster+") p LEFT JOIN tickets t ON t.engineer=p.name AND t.status != '已完成' GROUP BY p.name HAVING COUNT(t.id)=0 ORDER BY p.name LIMIT 50";route='idle_people'
    elif special=='review' or any(w in question for w in ['待審核','待主管審核','主管審核','等主管']):
        sql="SELECT id,machine,issue,engineer,status,created_at FROM tickets WHERE status='待主管審核' ORDER BY created_at LIMIT 50";route='tickets'
    elif (machine or any(w in question for w in ['機台','機器','設備','哪台','幾台'])) and any(w in question for w in ['檢查','檢修','保養','維修','異常','警示','風險','危險','健康','有哪些','幾台']) and not any(w in question for w in ['工單','維修紀錄','任務','報修']):
        sql="SELECT id, json_extract(payload, '$.name') AS name, json_extract(payload,'$.util') AS utilization, (SELECT min(json_extract(value,'$[1]')) FROM json_each(json_extract(payload,'$.parts'))) AS health FROM machines WHERE active=1"
        if machine:sql+=' AND id=:machine';params['machine']=machine
        elif any(w in question for w in ['檢查','檢修','保養','維修','異常','警示','風險','危險']):sql+=' AND (SELECT min(json_extract(value,\'$[1]\')) FROM json_each(json_extract(payload,\'$.parts\'))) < 70'
        sql+=' ORDER BY health IS NULL, health ASC LIMIT 50'
        route='machines'
    elif special in ['unassigned','open_tickets','history'] or any(w in question for w in ['工單','維修紀錄','維修過','報修','任務','派工']) and not any(w in question for w in ['負荷','最忙','最多任務','任務最多']):
        sql='SELECT id,machine,issue,engineer,status,created_at FROM tickets WHERE 1=1'
        if machine:sql+=' AND machine=:machine';params['machine']=machine
        name=next((p['name'] for p in people() if p['name'].lower() in question.lower()),None)
        if name:sql+=' AND engineer=:engineer';params['engineer']=name
        if special in ['unassigned','open_tickets'] or any(w in question for w in ['未完成','未結案','待處理','任務','未派工']):sql+=" AND status != '已完成'"
        if special=='unassigned' or any(w in question for w in ['未派工','未指派','沒派','沒指定']):sql+=" AND engineer = '待指派'"
        sql+=' ORDER BY created_at DESC LIMIT 50';route='tickets'
    elif special=='workload' or any(w in question for w in ['誰','人員','技師','工程師']) and any(w in question for w in ['負荷','忙','任務','空閒','工作量','最多']):
        sql="SELECT engineer,COUNT(*) AS open_tasks FROM tickets WHERE status != '已完成' GROUP BY engineer ORDER BY open_tasks DESC LIMIT 50";route='workload'
    else:return None
    if store.engine.dialect.name!='sqlite':return {'answer':'此自然語言查詢原型目前使用 SQLite，PostgreSQL 查詢模板尚未適配。','route':'database','llm_used':False,'rows':[],'sql':None}
    with store.Session() as s:rows=[dict(r) for r in s.execute(text(sql),params).mappings().all()]
    if route=='machines':
        answer=('依目前設備資料，'+str(len(rows))+' 台符合條件：\n'+'\n'.join(f"{r['id']} · {r['name']} · "+('健康度未知' if r['health'] is None else f"{'警示' if r['health']<45 else '注意' if r['health']<70 else '正常'} · 健康 {r['health']}%") for r in rows)) if rows else '目前沒有符合條件的設備。'
        answer+='\n零件健康為 DEMO 設定，僅用來示範巡檢排序。'
    elif route=='idle_people':answer=('目前沒有未結案工單的人員（'+str(len(rows))+' 位）：\n'+'\n'.join(r['engineer'] for r in rows)+'\n無工單不等於當班可用，派工前仍需確認班別。') if rows else '所有人員目前都有未結案工單。'
    elif route=='tickets':answer=('找到 '+str(len(rows))+' 筆工單：\n'+'\n'.join(f"{r['machine']} · {r['issue']} · {r['engineer']} · {r['status']}" for r in rows)) if rows else '目前沒有符合條件的工單。'
    else:answer=('未結案任務：\n'+'\n'.join(f"{r['engineer']}：{r['open_tasks']} 筆" for r in rows)) if rows else '目前沒有未結案任務。'
    return {'answer':answer,'route':'database','query_kind':route,'sql':sql,'parameters':params,'rows':rows,'llm_used':False,'method':'intent_classifier_and_rules_to_parameterized_sql','intent_model':'zh-maintenance-intent-v1','intent':intent,'intent_score':score,'machine_ids':list(dict.fromkeys(r.get('machine',r.get('id')) for r in rows if str(r.get('machine',r.get('id',''))).startswith('CNC-'))),'limit':50}

def register(app):
    @app.post('/api/chat')
    async def chat(body:ChatInput):
        q=body.text.strip()
        if any(w in q for w in ['這台','那台','它的']) and not re.search(r'CNC',q,re.I):
            context=next((str(h.get('content','')) for h in reversed(body.history) if h.get('role')=='user' and re.search(r'CNC[- ]?\d+',str(h.get('content','')),re.I)),None)
            if context:q+=' '+re.search(r'CNC[- ]?\d+',context,re.I).group(0)
        if any(w in q for w in ['薪水','薪資','薪酬','時薪','手機號','電話號','證照號','生日','住址','年薪']):return unknown('我不知道：目前沒有保存這項人員資料，不能推測或編造。')
        codes=re.findall(r'\bE\d{3}\b',q,re.I)
        if any(code.upper()!='E102' for code in codes):return unknown('我不知道這個警報碼的意思：目前只收錄 DEMO E102。請提供廠牌、控制器、機型與完整警報文字或手冊。')
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
        # A tiny local model sometimes returns only a citation ID. Show evidence when the answer is unusable.
        if len(result['answer'])<35 or re.fullmatch(r'(附文件編號[:：]?\s*)?[A-Z0-9-]+',result['answer'].strip()):
            if result['citations']:
                d=result['citations'][0];result['answer']='依 '+d['title']+'：\n'+d['text'];result['answer_method']='retrieved_document_fallback'
        result['machine_ids']=[]
        return result
