#!/usr/bin/env python3
"""Tela de terminal no navegador para o agente local. Só escuta em 127.0.0.1.

Uso: python3 agent/server.py [--port 8080]  →  http://127.0.0.1:8080
"""
import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import agent  # noqa: E402

PAGE = r"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<title>solvis · agente local</title>
<style>
 body{margin:0;background:#0b0b0b;color:#d0d0d0;font:14px/1.5 ui-monospace,Menlo,monospace}
 #log{padding:16px 20px 90px;white-space:pre-wrap}
 .u{color:#7fd1ff}.a{color:#e6e6e6}.t{color:#777}.ok{color:#5fd068}.warn{color:#ffb454}.err{color:#ff6b6b}
 table{border-collapse:collapse;margin:6px 0}td,th{border:1px solid #333;padding:2px 8px;text-align:left}
 th{color:#aaa}svg{display:block;margin:6px 0}
 #bar{position:fixed;bottom:0;left:0;right:0;background:#111;border-top:1px solid #333;display:flex;padding:10px 20px}
 #bar span{color:#5fd068;margin-right:8px}#q{flex:1;background:transparent;border:0;color:#fff;font:inherit;outline:0}
</style></head><body>
<div id="log"><span class="t">solvis agente local · modelo MODEL · dados: ClickHouse 127.0.0.1 (usuário isolado)
o modelo escolhe ferramentas fixas; números vêm só do ClickHouse e são conferidos na resposta.
comandos: /limpar  /trace (mostra ou esconde as chamadas)
</span></div>
<div id="bar"><span>solvis&gt;</span><input id="q" autofocus autocomplete="off" placeholder="ex.: NPS da Satisfação ontem por Regional"></div>
<script>
const log=document.getElementById('log'),q=document.getElementById('q');let hist=[],showTrace=true;
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function add(h){log.insertAdjacentHTML('beforeend',h);window.scrollTo(0,document.body.scrollHeight)}
function tableHtml(rows){if(!rows.length)return'';const k=Object.keys(rows[0]);
 return '<table><tr>'+k.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr>'+rows.map(r=>'<tr>'+k.map(x=>'<td>'+esc(r[x]??'')+'</td>').join('')+'</tr>').join('')+'</table>'}
function chart(rows){const vk=['nps','share_pct','mean','evaluations'].find(k=>rows[0]&&k in rows[0]);
 const lk=['value','unit','text','letter'].find(k=>rows[0]&&k in rows[0]);if(!vk||!lk||rows.length<2)return'';
 const vals=rows.map(r=>+r[vk]),max=Math.max(...vals.map(Math.abs),1),h=18,w=360;
 return '<svg width="'+(w+260)+'" height="'+(rows.length*h+4)+'">'+rows.map((r,i)=>{const bw=Math.abs(+r[vk])/max*w;
  return '<text x="0" y="'+(i*h+13)+'" fill="#aaa" font-size="12">'+esc(String(r[lk]).slice(0,22))+'</text>'+
  '<rect x="170" y="'+(i*h+3)+'" width="'+bw+'" height="'+(h-6)+'" fill="'+(+r[vk]<0?'#ff6b6b':'#5fd068')+'"/>'+
  '<text x="'+(176+bw)+'" y="'+(i*h+13)+'" fill="#ddd" font-size="12">'+esc(r[vk])+(r.n!==undefined?'  (n='+esc(r.n)+')':'')+'</text>'}).join('')+'</svg>'}
q.addEventListener('keydown',async e=>{if(e.key!=='Enter'||!q.value.trim())return;const text=q.value.trim();q.value='';
 if(text==='/limpar'){hist=[];log.innerHTML='';return}
 if(text==='/trace'){showTrace=!showTrace;add('<span class="t">trace '+(showTrace?'ligado':'desligado')+'\n</span>');return}
 add('<span class="u">&gt; '+esc(text)+'</span>\n<span class="t" id="wait">pensando...</span>\n');hist.push({role:'user',content:text});
 const t0=Date.now();let d;try{const r=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({history:hist})});d=await r.json()}catch(err){d={error:String(err)}}
 document.getElementById('wait').remove();
 if(d.error){add('<span class="err">erro: '+esc(d.error)+'</span>\n\n');hist.pop();return}
 if(showTrace)d.trace.forEach(c=>add('<span class="t">  ↳ '+esc(c.tool)+' '+esc(JSON.stringify(c.args))+' → '+(c.ok?c.rows+' linhas':'<span class=err>erro</span>')+'</span>\n'));
 if(d.table){add(tableHtml(d.table.rows));add(chart(d.table.rows))}
 add('<span class="a">'+esc(d.answer)+'</span>\n');
 add(d.verified?'<span class="ok">✓ números conferidos com o ClickHouse</span>':'<span class="warn">⚠ números sem origem nas ferramentas: '+esc(d.unverified_numbers.join(', '))+'</span>');
 add('<span class="t">  '+((Date.now()-t0)/1000).toFixed(1)+' s</span>\n\n');hist.push({role:'assistant',content:d.answer})});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path != "/":
            return self._send(404, "não encontrado", "text/plain; charset=utf-8")
        self._send(200, PAGE.replace("MODEL", agent.MODEL), "text/html; charset=utf-8")

    def do_POST(self):
        if self.path != "/ask":
            return self._send(404, "{}", "application/json")
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 200_000)))
            history = [{"role": m["role"], "content": str(m["content"])[:4000]}
                       for m in body.get("history", [])[-12:] if m.get("role") in ("user", "assistant")]
            out = agent.ask(history, source="ui")
        except Exception as e:  # protótipo: devolve o erro para a tela
            out = {"error": f"{type(e).__name__}: {e}"}
        self._send(200, json.dumps(out, ensure_ascii=False, default=str), "application/json; charset=utf-8")

    def log_message(self, fmt, *args):
        sys.stderr.write("%s\n" % (fmt % args))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    port = ap.parse_args().port
    print(f"http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
