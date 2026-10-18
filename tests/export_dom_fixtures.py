import sys,json,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'tests')]
import server
from test_api import official
from fastapi.testclient import TestClient
server.DB_PATH=Path(tempfile.mkdtemp())/'db.sqlite'
async def fake(base,path='',*,params=None,ttl=60):
 return official(path if base in (server.GMB,server.KMB,server.CTB) else ('/v1/transport/mtr/getSchedule.php' if base==server.MTR else '/weatherAPI/opendata/weather.php'))
server.upstream=fake
paths=['/api/gmb/routes/HKI','/api/gmb/route/HKI/69','/api/gmb/stops/2000410/1','/api/gmb/stop/20003337','/api/gmb/eta/2000410/1/1','/api/bus/kmb/stops?route=1A&direction=outbound&service_type=1','/api/bus/kmb/eta?route=1A&stop_id=A3ADFCDF8487ADB9&direction=outbound&service_type=1','/api/bus/kmb/stop/A3ADFCDF8487ADB9','/api/bus/ctb/stops?route=1&direction=inbound','/api/bus/ctb/eta?route=1&stop_id=002403&direction=inbound','/api/bus/ctb/stop/002403','/api/weather','/api/mtr/next-train?line=TKL&station=TKO','/api/lab/summary','/api/ai/status','/api/diagnostics']
with TestClient(server.app) as c:
 data={p:c.get(p).json() for p in paths}
 data['/api/ai/interpret-preferences']=c.post('/api/ai/interpret-preferences',json={'text':'Less walking and fewer transfers'}).json()
Path(sys.argv[1]).write_text(json.dumps(data))
