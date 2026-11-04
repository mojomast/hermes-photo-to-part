import sqlite3,sys,re,json,datetime
log=open(sys.argv[1]).read(); m=re.findall(r'Session:\s+(\S+)',log)
if not m: print('NOSESSION');sys.exit()
sid=m[-1]; c=sqlite3.connect(os.path.join(os.environ['HERMES_HOME'],'state.db')); c.row_factory=sqlite3.Row
cols=[r[1] for r in c.execute('pragma table_info(messages)')]
tcol='timestamp' if 'timestamp' in cols else ('created_at' if 'created_at' in cols else None)
out=open(sys.argv[2],'w')
for r in c.execute('select * from messages where session_id=? order by id',(sid,)):
    ts=r[tcol] if tcol else ''
    try: ts=datetime.datetime.fromtimestamp(float(ts)).strftime('%Y-%m-%dT%H:%M:%S')
    except: pass
    tc=r['tool_calls']
    if tc:
        for t in json.loads(tc):
            f=t['function']; out.write(f"{ts} TOOLCALL {f['name']} {f['arguments'][:600]}\n")
    out.write(f"{ts} {r['role']}: {(r['content'] or '')[:1500]}\n")
print(sid)
