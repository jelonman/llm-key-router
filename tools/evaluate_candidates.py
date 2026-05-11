#!/usr/bin/env python3
from pathlib import Path
import argparse,json,time,urllib.error,urllib.request
PROMPT='Return JSON only with exactly this shape: {"route_ok": true, "safe_next_step": "one safe read-only next step", "do_not_do": ["item one", "item two", "item three"], "score": 1}. Do not mention secrets, account automation, payments, installs, Docker, sudo, or destructive cleanup.'
def call(alias,url,timeout):
    payload={'model':alias,'messages':[{'role':'system','content':'Return valid JSON only. No markdown. No reasoning.'},{'role':'user','content':PROMPT}],'temperature':0,'max_tokens':450,'stream':False,'reasoning':{'exclude':True}}
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer local'},method='POST'); t=time.time()
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            data=json.loads(r.read().decode()); content=data['choices'][0]['message'].get('content') or ''; valid=False; parsed=None
            try: parsed=json.loads(content); valid=isinstance(parsed,dict)
            except Exception: pass
            return {'alias':alias,'status':r.status,'provider':r.headers.get('X-LLM-Key-Router-Provider'),'credential':r.headers.get('X-LLM-Key-Router-Credential'),'actual_model':data.get('model'),'elapsed_sec':round(time.time()-t,2),'completion_tokens':data.get('usage',{}).get('completion_tokens'),'valid_json':valid,'parsed':parsed,'content_preview':content[:800]}
    except urllib.error.HTTPError as e: return {'alias':alias,'http_error':e.code,'body':e.read().decode('utf-8',errors='replace')[:1200]}
    except Exception as e: return {'alias':alias,'error':repr(e)}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--url',default='http://127.0.0.1:8080/v1/chat/completions'); ap.add_argument('--aliases',nargs='+',required=True); ap.add_argument('--out',default='state/evaluation_latest.json'); ap.add_argument('--timeout',type=int,default=180); ap.add_argument('--pause',type=float,default=3); args=ap.parse_args()
    results=[]
    for a in args.aliases:
        print(f'=== {a} ==='); r=call(a,args.url,args.timeout); print(json.dumps(r,indent=2,ensure_ascii=False)); results.append(r); time.sleep(args.pause)
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps({'created_epoch':time.time(),'results':results},indent=2,ensure_ascii=False)+'\n',encoding='utf-8'); print(f'Saved {out}')
if __name__=='__main__': main()
