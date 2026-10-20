import hashlib, hmac, secrets, os, time, json
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from threading import Lock
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from . import store, config
COOKIE='predictfix_session'
ATTEMPTS={}
attemptsLock = Lock()


def sameOrigin(origin, url):
  try:
    parsed = urlparse(origin)
    return parsed.scheme == url.scheme and parsed.netloc == url.netloc
  except ValueError:
    return False
def password_hash(password,salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),310000).hex()
def seed(people):
    if not config.demo():
        with store.Session() as db:
            if db.query(store.User).count():
                return
            password=os.getenv('BOOTSTRAP_PASSWORD', '')
            if len(password)<16:
                raise RuntimeError('First production startup requires BOOTSTRAP_PASSWORD (16+ characters)')
            db.add(store.User(username='supervisor',name='管理員',role='supervisor',password_hash=password_hash(password)))
            db.commit()
        return
    accounts=[('supervisor','陳主管','supervisor')]+[(p['name'].split()[0].lower(),p['name'],'engineer') for p in people]
    created=[]
    with store.Session() as db:
        for username,name,role in accounts:
            if db.get(store.User,username):continue
            password=os.getenv('BOOTSTRAP_PASSWORD') or secrets.token_urlsafe(15)
            db.add(store.User(username=username,name=name,role=role,password_hash=password_hash(password)))
            created.append(dict(username=username,name=name,role=role,password=password))
        db.commit()
    if created and not os.getenv('BOOTSTRAP_PASSWORD'):
        path=store.ROOT/'data'/'initial-accounts.json'
        existing=json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
        path.write_text(json.dumps(existing+created,ensure_ascii=False,indent=2),encoding='utf-8')
def supervisor(request):
    if request.state.user['role']!='supervisor':raise HTTPException(403,'此操作需要主管權限')
def assigned(request,ticket):
    if ticket.engineer!=request.state.user['name']:raise HTTPException(403,'只能操作指派給自己的工單')
def register(app):
    @app.middleware('http')
    async def authorize(request:Request,call_next):
        if not request.url.path.startswith('/api/'):return await call_next(request)
        if request.method not in ['GET','HEAD']:
            origin=request.headers.get('origin')
            if origin and not sameOrigin(origin, request.url):return JSONResponse({'detail':'不允許跨站請求'},status_code=403)
        if request.url.path in ['/api/auth/login','/api/auth/config','/api/auth/demo']:return await call_next(request)
        # 機器驗證僅適用單一 POST 入口，其餘介接管理仍走 session 與 CSRF。
        if request.method=='POST' and request.url.path=='/api/integrations/work-orders':
            from .integration_service import verifyRequest
            try:
                await verifyRequest(request)
            except HTTPException as error:
                return JSONResponse({'detail':error.detail},status_code=error.status_code)
            return await call_next(request)
        token=request.cookies.get(COOKIE,'')
        with store.Session() as db:
            session=db.get(store.LoginSession,hashlib.sha256(token.encode()).hexdigest()) if token else None
            user=db.get(store.User,session.username) if session else None
            if not session or not user or not user.active or session.expires_at.replace(tzinfo=timezone.utc)<=datetime.now(timezone.utc):return JSONResponse({'detail':'請先登入'},status_code=401)
            request.state.user=dict(username=user.username,name=user.name,role=user.role)
            request.state.session_hash=session.token_hash;request.state.csrf=session.csrf
            csrfToken = request.headers.get('x-csrf-token', '')
            if request.method not in ['GET','HEAD'] and (not csrfToken.isascii() or not hmac.compare_digest(csrfToken,session.csrf)):return JSONResponse({'detail':'驗證碼失效，請重新登入'},status_code=403)
        return await call_next(request)
    @app.get('/api/auth/config')
    def auth_config():
        enabled=config.demo() and not config.lan() and os.getenv('DEMO_MODE')=='1'
        with store.Session() as db:
            user=db.get(store.User,'interview_demo') if enabled else None
            interview=bool(user and user.active and user.role=='engineer')
        return {'demo_mode':enabled,'app_mode':'demo' if config.demo() else 'production',
                'interview_demo_available':interview,'lan_mode':config.lan()}
    class DemoLogin(BaseModel):
        role:str=Field(pattern=r'^(supervisor|engineer)$')
        username:str=Field(default='',max_length=50)
    @app.post('/api/auth/demo')
    def demo(body:DemoLogin,request:Request):
        if config.lan() or not config.demo() or os.getenv('DEMO_MODE')!='1':raise HTTPException(403,'DEMO 快速登入未開啟')
        username='supervisor' if body.role=='supervisor' else (body.username or 'amy')
        with store.Session() as db:
            user=db.get(store.User,username)
            if not user or not user.active or user.role!=body.role:raise HTTPException(403,'展示帳號未啟用或角色不符')
            old=request.cookies.get(COOKIE)
            if old:
                previous=db.get(store.LoginSession,hashlib.sha256(old.encode()).hexdigest())
                if previous:db.delete(previous)
            token=secrets.token_urlsafe(32);csrf=secrets.token_hex(32)
            db.add(store.LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),username=username,csrf=csrf,expires_at=datetime.now(timezone.utc)+timedelta(hours=1)))
            db.add(store.Audit(kind='demo_login',request_id=secrets.token_hex(16),payload=json.dumps({'username':username,'role':user.role})));db.commit()
            result=JSONResponse({'user':dict(username=user.username,name=user.name,role=user.role),'csrf':csrf})
            result.set_cookie(COOKIE,token,httponly=True,samesite='strict',secure=os.getenv('COOKIE_SECURE')=='1',max_age=3600);return result
    class Login(BaseModel):
        username:str=Field(min_length=1,max_length=50)
        password:str=Field(min_length=1,max_length=200)
    @app.post('/api/auth/login')
    def login(body:Login,request:Request):
        key = (request.client.host, body.username.lower())
        # 先保留此次嘗試的額度，避免並行驗證互相覆蓋失敗次數。
        with attemptsLock:
          now = time.monotonic()
          recent = [attempt for attempt in ATTEMPTS.get(key, []) if now - attempt < 300]
          if len(recent) >= 5:
            raise HTTPException(429, '登入失敗次數過多，請五分鐘後再試')
          recent.append(now)
          ATTEMPTS[key] = recent
        with store.Session() as db:
            user=db.get(store.User,body.username.lower());encoded=user.password_hash if user else password_hash('invalid')
            valid=hmac.compare_digest(password_hash(body.password,encoded.split(':')[0]),encoded)
            if not user or not user.active or not valid:
                raise HTTPException(401,'帳號或密碼錯誤')
            with attemptsLock:
              ATTEMPTS.pop(key,None)
            old=request.cookies.get(COOKIE)
            if old:
                existing=db.get(store.LoginSession,hashlib.sha256(old.encode()).hexdigest())
                if existing:db.delete(existing)
            token=secrets.token_urlsafe(32);csrf=secrets.token_hex(32)
            db.add(store.LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),username=user.username,csrf=csrf,expires_at=datetime.now(timezone.utc)+timedelta(hours=8)));db.commit()
            result=JSONResponse({'user':dict(username=user.username,name=user.name,role=user.role),'csrf':csrf})
            result.set_cookie(COOKIE,token,httponly=True,samesite='strict',secure=os.getenv('COOKIE_SECURE')=='1',max_age=28800);return result
    @app.get('/api/auth/me')
    def me(request:Request):return {'user':request.state.user,'csrf':request.state.csrf}
    @app.post('/api/auth/logout')
    def logout(request:Request):
        with store.Session() as db:
            session=db.get(store.LoginSession,request.state.session_hash)
            if session:db.delete(session);db.commit()
        result=JSONResponse({'ok':True});result.delete_cookie(COOKIE);return result
