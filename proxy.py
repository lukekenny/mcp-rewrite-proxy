#!/usr/bin/env python3
import http.server
import socketserver
import json
import requests

UPSTREAM="http://firecrawl:8030/mcp"

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length=int(self.headers.get('content-length',0))
        body=self.rfile.read(length).decode("utf-8")
        try:
            data=json.loads(body)
            if data.get("method")=="initialize" and data.get("params",{}).get("capabilities",{})=={}:
                data["params"]["capabilities"]={"tools":{},"resources":{},"logging":{}}
                body=json.dumps(data)
        except Exception:
            pass
        r=requests.post(UPSTREAM,headers={"Content-Type":"application/json"},data=body,stream=True)
        self.send_response(r.status_code)
        for k,v in r.headers.items():
            if k.lower()=="transfer-encoding": continue
            self.send_header(k,v)
        self.end_headers()
        for chunk in r.iter_content(chunk_size=None):
            self.wfile.write(chunk)

if __name__=="__main__":
    with socketserver.TCPServer(("0.0.0.0",9000),Handler) as httpd:
        httpd.serve_forever()
