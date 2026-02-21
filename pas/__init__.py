import wsgiref
import os
import webbrowser
import time
import uuid
import cgi
import sys
import magic
from collections import defaultdict, deque
from typing import Callable, Any, Dict, List, Optional, Union, Deque, Iterable
try:
    from urllib.parse import parse_qs, unquote
except ImportError:
    from urlparse import parse_qs, unquote
from wsgiref.util import setup_testing_defaults, shift_path_info, request_uri
from wsgiref.simple_server import make_server
from jinja2 import Environment, FileSystemLoader

__version__ = "0.1.0"

IP_LOGS: Dict[str, Deque[float]] = defaultdict(lambda: deque())
MAX_REQ_PER_SECOND = 25
rate_limit = True

def rate_limiter(ip: str) -> bool:
    now = time.time()
    log = IP_LOGS[ip]
    while log and log[0] < now - 1:
        log.popleft()
    if len(log) >= MAX_REQ_PER_SECOND:
        return False
    log.append(now)
    return True

class sessionitem():
    def __init__(self, sessionid: str):
        self.session = sessionid
    def __getitem__(self, key: str) -> Any:
        return session[self.session][key]
    def __setitem__(self, key: str, val: Any) -> None:
        session[self.session][key] = val

class request():
    def __init__(self, method: str, path: str, ip: str, ua: str, host: str, 
                 cookie: Dict[str, str], header: Dict[str, Any], 
                 data: Dict[str, Any], postdata: Dict[str, Any], sessionid: str):
        self.method = method
        self.path = path
        self.ip = ip
        self.ua = ua
        self.host = host
        self.cookie = cookie
        self.header = header
        self.data = data
        self.post = postdata
        self.item = sessionitem(sessionid)

class mimeset():
    def __init__(self, data: bytes, mimetype: str):
        self.data = data
        self.mime = mimetype

class responce():
    def __init__(self, data: bytes, responce: str):
        self.data = data
        self.datas = responce

class file():
    def __init__(self, filename: str, download: bool = False, name: Optional[str] = None):
        mime = magic.Magic(mime=True)
        self.mimetype: str = mime.from_file(filename)
        self.download = download
        self.name = name if name else filename
        self.filename = filename

class WebsocketObject():
    def __init__(self) -> None:
        self.connect: Optional[Callable] = None
        self.receive: Optional[Callable] = None
        self.disconnect: Optional[Callable] = None
    def disconnect_set(self, func: Callable) -> Callable:
        self.disconnect = func
        return func
    def receive_set(self, func: Callable) -> Callable:
        self.receive = func
        return func
    def connect_set(self, func: Callable) -> Callable:
        self.connect = func
        return func

def nodatafunc(aa: request) -> str:
    return "NoData"

pagefunc: Dict[str, Any] = {
    "GET": nodatafunc,
    "POST": nodatafunc,
    "PUT": nodatafunc,
    "DELETE": nodatafunc,
    "WebSocket": None,
}

setting: Dict[str, str] = {
    "template": "./",
    "static_folder": "./static/",
}

session: Dict[str, Dict[str, Any]] = {}

def session_set() -> str:
    sessionid = str(uuid.uuid4())
    session[sessionid] = {}
    return sessionid

def template(filename: str, **data: Any) -> str:
    env = Environment(loader=FileSystemLoader('./', encoding='utf8'))
    tmpl = env.get_template(setting["template"] + filename)
    return tmpl.render(data)

def get(func: Callable) -> Callable:
    pagefunc["GET"] = func
    return func

def post(func: Callable) -> Callable:
    pagefunc["POST"] = func
    return func

def put(func: Callable) -> Callable:
    pagefunc["PUT"] = func
    return func

def delete(func: Callable) -> Callable:
    pagefunc["DELETE"] = func
    return func

def go(link: str, timee: int = 0) -> str:
    return f'<meta http-equiv="Refresh" content="{timee};URL={link}">'

@get
def samplepage(e: request) -> str:
    print(e.ip)
    return e.ip

apps: Dict[str, Any] = {}
headers: List[tuple] = []

def app(environ: Dict[str, Any], start_response: Callable) -> Iterable[bytes]:
    setup_testing_defaults(environ)
    global apps, headers
    if rate_limit and not rate_limiter(environ.get("REMOTE_ADDR", "")):
        start_response("429 Too Many Requests", [("Content-Type", "text/plain")])
        return [b"Too Many Requests"]
    apps = environ
    status = '200 OK'
    headers = [('Content-type', 'text/html; charset=utf-8')]
    wsgi_input = environ["wsgi.input"]
    form = cgi.FieldStorage(fp=wsgi_input, environ=environ, keep_blank_values=True)
    
    raw_cookie = environ.get("HTTP_COOKIE", "")
    cookie_dict = {}
    if raw_cookie:
        for i in raw_cookie.split("; "):
            if "=" in i:
                k, v = i.split("=", 1)
                cookie_dict[k] = v

    path_info = "/".join(request_uri(environ).split("/")[3:])
    
    if "." in request_uri(environ):
        sid = ""
    elif "session" not in cookie_dict:
        sid = session_set()
        headers.append(('Set-Cookie', f'session={sid}'))
    else:
        sid = cookie_dict["session"]
        if sid not in session:
            sid = session_set()
            headers.append(('Set-Cookie', f'session={sid}'))

    e = request(environ["REQUEST_METHOD"],
                path_info,
                environ.get("REMOTE_ADDR", ""),
                environ.get("HTTP_USER_AGENT", ""),
                environ.get("HTTP_HOST", ""),
                cookie_dict,
                environ,
                parse_qs(environ.get("QUERY_STRING", "")),
                {k: form[k].value for k in form.keys() if not isinstance(form[k], list)},
                sid)
    
    returns = pagefunc[environ["REQUEST_METHOD"]](e)
    
    if isinstance(returns, (dict, list)):
        headers = [('Content-type', 'application/json;')]
        ret = [str(returns).encode("utf-8")]
    elif isinstance(returns, file):
        headers = [('Content-type', f'{returns.mimetype};')]
        with open(returns.filename, mode='rb') as f:
            ret = [f.read()]
    elif isinstance(returns, mimeset):
        headers = [('Content-type', f'{returns.mime};')]
        ret = [returns.data]
    elif isinstance(returns, responce):
        headers = [('Content-type', f'{returns.datas};')]
        ret = [returns.data]
    else:
        ret = [str(returns).encode("utf-8")]
        
    start_response(status, headers)
    return ret

def run(port: int) -> None:
    with make_server('', port, app) as httpd:
        print(f"Serving on port {port}...")
        httpd.serve_forever()

async def speedapp_http(scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
    global headers
    headers = [['content-type', 'text/html;charset=utf-8']]
    more_body = True
    body_bytes = b""
    while more_body:
        msg = await receive()
        body_bytes += msg.get('body', b'')
        more_body = msg.get('more_body', False)

    def txtorint(x: str) -> str:
        try:
            return chr(int(x))
        except (ValueError, TypeError):
            return x

    body_str = body_bytes.decode("utf-8", errors="ignore")
    try:
        post_data = {}
        for item in body_str.split("&"):
            if "=" in item:
                k, v = item.split("=", 1)
                decoded_v = "".join([txtorint(i) for i in unquote(v).replace("&#", "").split(";") if i])
                post_data[k] = decoded_v
    except Exception:
        post_data = {}

    query_string = scope.get("query_string", b"").decode("utf-8")
    try:
        datas = {k: v[0] for k, v in parse_qs(query_string).items()}
    except Exception:
        datas = {}

    e = request(scope["method"],
                scope["path"],
                scope.get("client", ["", ""])[0],
                "", # UA extraction from scope headers is complex, left as placeholder
                "", # Host placeholder
                {}, # Cookie placeholder
                scope,
                datas,
                post_data,
                "") # Session placeholder for ASGI

    handler = pagefunc[scope["method"]]
    if hasattr(handler, '__call__'):
        if sys.version_info >= (3, 7): # Simple check for async handler
            import inspect
            if inspect.iscoroutinefunction(handler):
                returns = await handler(e)
            else:
                returns = handler(e)
        else:
            returns = handler(e)
    else:
        returns = "NoData"

    if isinstance(returns, file):
        headers[0] = ['content-type', f'{returns.mimetype};']
        with open(returns.filename, mode='rb') as f:
            resp_body = f.read()
    else:
        resp_body = str(returns).encode("utf-8")

    await send({
        'type': 'http.response.start',
        'status': 200,
        'headers': [[str(i2).encode("utf-8") for i2 in i] for i in headers]
    })
    await send({
        'type': 'http.response.body',
        'body': resp_body,
    })

async def speedapp(scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
    if scope['type'] == 'http':
        await speedapp_http(scope, receive, send)
    elif scope["type"] == "websocket" and pagefunc["WebSocket"]:
        while True:
            event = await receive()
            if event['type'] == 'websocket.connect':
                await pagefunc["WebSocket"].connect(send, event)
            if event['type'] == 'websocket.disconnect':
                await pagefunc["WebSocket"].disconnect(send, event)
                break
            if event['type'] == 'websocket.receive':
                await pagefunc["WebSocket"].receive(send, event)







