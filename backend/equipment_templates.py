"""Single-factory equipment schemas; template snapshots do not change existing assets."""
import json
import uuid
from typing import Literal
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, update
from . import store, auth, repair_flow
from .evidence import UNITS


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Measure(Input):
    label: str = Field(min_length=2, max_length=50)
    metric: Literal['temperature','vibration','current','pressure','speed','deviation']

    @field_validator('label')
    @classmethod
    def clean(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('量測名稱不可空白')
        return value.strip()


class TemplateInput(Input):
    name: str = Field(min_length=2, max_length=80)
    asset_type: str = Field(min_length=2, max_length=80)
    kind: Literal['mill','lathe']
    parts: list[str] = Field(min_length=1, max_length=16)
    measurements: list[Measure] = Field(default_factory=list, max_length=6)
    steps: list[repair_flow.Step] = Field(min_length=2, max_length=16)
    description: str = Field(default='', max_length=500)

    @field_validator('name','asset_type')
    @classmethod
    def clean(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('名稱不可空白')
        return value.strip()

    @field_validator('parts')
    @classmethod
    def clean_parts(cls, values):
        values = [v.strip() for v in values]
        if any(not v or len(v)>50 for v in values) or len(set(values))!=len(values):
            raise ValueError('零件名稱不可空白、重複或超過50字')
        return values

    @model_validator(mode='after')
    def validate_structure(self):
        if len({m.metric for m in self.measurements}) != len(self.measurements):
            raise ValueError('量測種類不可重複')
        if {s.kind for s in self.steps} != {'inspect','verify'}:
            raise ValueError('至少一項排查與一項驗收')
        if any(s.source_chunk_id or s.source_hash for s in self.steps):
            raise ValueError('模板項目不預先綁定手冊；工單核准時另行確認來源')
        return self


class TemplateUpdate(TemplateInput):
    revision: int = Field(ge=1)


def builtin(kind):
    lathe=kind=='lathe'
    return {'id':'builtin-'+kind,'revision':1,'builtin':True,
        'name':'CNC 車床基礎模板' if lathe else 'CNC 加工中心基礎模板',
        'asset_type':'CNC 車床' if lathe else 'CNC 加工中心','kind':kind,
        'description':'結構與記錄欄位模板；不代表原廠維修程序或驗收標準。主管須依實際機型調整。',
        'parts':['主軸軸承','車削刀片' if lathe else '切削刀具','液壓泵' if lathe else '冷卻泵','進給螺桿'],
        'measurements':[{'label':'主軸溫度','metric':'temperature'},{'label':'主軸振動','metric':'vibration'},
                        {'label':'定位偏差','metric':'deviation'}],
        'steps':[{'label':'核對異常與適用機型','kind':'inspect','criterion':'記錄警報、發生條件及已查項目，依適用文件確認排查範圍'},
                 {'label':'維修後復測與驗收','kind':'verify','criterion':'依主管核准的機型標準記錄測試條件與實際結果；未測範圍保留未驗證'}]}


def get_template(db, template_id):
    if template_id in ('builtin-mill','builtin-lathe'):
        return builtin(template_id.split('-')[1])
    row=db.get(store.EquipmentTemplate,template_id)
    if not row:
        raise HTTPException(422,'設備模板不存在')
    return {'id':row.id,'revision':row.revision,'builtin':False,**json.loads(row.payload)}


def machine_payload(body, db):
    template=get_template(db, body.template_id or 'builtin-'+body.kind)
    if template['kind'] != body.kind:
        raise HTTPException(422,'示意類型與設備模板不一致')
    return {**body.model_dump(exclude={'template_id'}),'name':body.name.strip(),
        'parts':[[name,None,0,0,None,'尚無量測資料，健康度未知。'] for name in template['parts']],
        'util':None,'hours':None,'status':'待建檔','risk':None,'temp':None,'vib':None,
        'source':'user_created','asset_type':template['asset_type'],'equipment_template':template,
        'measurement_fields':[{**m,'unit':UNITS[m['metric']]} for m in template['measurements']]}


def register(app):
    @app.get('/api/equipment-templates')
    def list_templates():
        with store.Session() as db:
            return [builtin('mill'),builtin('lathe')]+[get_template(db,t.id) for t in
                db.scalars(select(store.EquipmentTemplate).order_by(store.EquipmentTemplate.id)).all()]

    @app.post('/api/equipment-templates',status_code=201)
    def create_template(body:TemplateInput,request:Request):
        auth.supervisor(request)
        tid='TPL-'+uuid.uuid4().hex[:16]
        with store.Session() as db:
            db.add(store.EquipmentTemplate(id=tid,revision=1,payload=json.dumps(body.model_dump(),ensure_ascii=False)))
            db.add(store.Audit(kind='equipment_template_created',request_id=uuid.uuid4().hex,
                payload=json.dumps({'id':tid,'actor':request.state.user['username']})))
            db.commit()
            return get_template(db,tid)

    @app.put('/api/equipment-templates/{tid}')
    def update_template(tid:str,body:TemplateUpdate,request:Request):
        auth.supervisor(request)
        if tid.startswith('builtin-'):
            raise HTTPException(409,'內建模板請另存副本後編輯')
        with store.Session() as db:
            if not db.get(store.EquipmentTemplate,tid):
                raise HTTPException(404,'設備模板不存在')
            result=db.execute(update(store.EquipmentTemplate).where(store.EquipmentTemplate.id==tid,
                store.EquipmentTemplate.revision==body.revision).values(revision=body.revision+1,
                payload=json.dumps(body.model_dump(exclude={'revision'}),ensure_ascii=False)))
            if result.rowcount!=1:
                raise HTTPException(409,'模板已更新，請重新載入')
            db.add(store.Audit(kind='equipment_template_updated',request_id=uuid.uuid4().hex,
                payload=json.dumps({'id':tid,'revision':body.revision+1,'actor':request.state.user['username']})))
            db.commit()
            return get_template(db,tid)
