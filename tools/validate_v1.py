"""Offline v1 checks: real game Lua race parser + settings, color headers/payloads.

Uses installed Lua math primitives. This is not an engine rendering test.
Installed game source is read locally and is not copied into the mod.
"""
import json
import struct
import sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).parent/'lib'))
import numpy as np
from lupa.luajit21 import LuaRuntime
from validation_images import open_texture
from convert_track import ai_read

base=Path(__file__).resolve().parents[1]
game=Path(sys.argv[1])
unpacked=base/'output/unpacked'
level=unpacked/'levels/st_stctk_ac_port'
folder=unpacked/'gameplay/missions/st_stctk_ac_port/timeTrial/001-full-circuit'
race=json.loads((folder/'race.race.json').read_text(encoding='utf-8'))
mission=json.loads((folder/'info.json').read_text(encoding='utf-8'))
lua=LuaRuntime(unpack_returned_tuples=True)
lua.execute('''
nop=function() end
table.clear=function(t) for k in pairs(t) do t[k]=nil end end
function deepcopy(t)
  if type(t)~='table' then return t end
  local o={} for k,v in pairs(t) do o[k]=deepcopy(v) end return o
end
-- Route navigation and side decoration are not exercised by these parser tests.
package.preload['/lua/ge/extensions/gameplay/route/route']=function() return function() return {} end end
''')
lua.execute((game/'lua/common/mathlib.lua').read_text(encoding='utf-8'))
modules=['gameplay/util/sortedList','gameplay/util/customFields','gameplay/race/pathnode',
         'gameplay/race/segment','gameplay/race/startPosition','gameplay/race/pacenote','gameplay/race/path']
loader=lua.eval('function(source,name) local fn=assert(loadstring(source,name)); package.preload[name]=fn end')
for name in modules:
    key='/lua/ge/extensions/'+name
    loader((game/(key.lstrip('/')+'.lua')).read_text(encoding='utf-8'),key)
def table(value):
    if isinstance(value,dict):return lua.table_from({k:table(v) for k,v in value.items()})
    if isinstance(value,list):return lua.table_from([table(v) for v in value])
    return value
path=lua.eval("require('/lua/ge/extensions/gameplay/race/path')")('Validation')
path.onDeserialized(path,table(race))
classification=path.classify(path)
assert classification.closed and classification.allowRollingStart
assert not classification.branching and not classification.reversible
assert len(path.pathnodes.sorted)==18 and len(path.segments.sorted)==18
ordered=[path.config.linearPathnodes[i] for i in range(1,len(path.config.linearPathnodes)+1)]
assert len(ordered)==19 and ordered[0]==ordered[-1] and len(set(ordered[:-1]))==18
assert not path.startPositions.objects[path.defaultStartPosition].missing
assert not path.startPositions.objects[path.rollingStartPosition].missing
# Run the installed mission constructor's settings and init against this data.
lua.execute('gameplay_missions_missions={flowMission=function(c,obj) return setmetatable(obj,c) end}')
constructor=lua.execute((game/'gameplay/missionTypes/timeTrial/constructor.lua').read_text(encoding='utf-8'))
obj=constructor(table(mission));obj.getCommonSettingsData=lua.eval('function() return {} end')
obj.setBackwardsCompatibility=lua.eval('function() end')
obj.init(obj)
settings=obj.getUserSettingsData(obj)
settings={s.key:s for _,s in settings.items()}
assert settings['laps'].min==1 and settings['laps'].max==20 and settings['laps'].value==3
assert not settings['laps'].disabled and settings['rolling'].type=='bool'
assert obj.fgPath=='/gameplay/missionTypes/timeTrial/ttFg.flow.json'
# Exercise actual native result calculation at and around all star boundaries,
# including a multi-lap race whose best lap is used for the rating.
star_keys=mission['careerSetup']['defaultStarKeys']
assert star_keys==['lapTime1','lapTime2','lapTime3']
assert set(k for k,v in mission['careerSetup']['starsActive'].items() if v)==set(star_keys)
for laps,expected in [([80.001],0),([80],1),([70.001],1),([70],2),([65.001],2),([65],3),([85,64,90],3)]:
    elapsed=0;historic=[]
    for lap in laps:
        elapsed+=lap;historic.append(dict(lapTime=lap,endTime=elapsed))
    attempt=table(dict(data={},unlockedStars={}))
    obj.lastUserSettings=table(dict(laps=len(laps)))
    obj.addAttemptData(obj,attempt,table(dict(playerVehId=1,penalty=0,raceData=dict(states={1:dict(historicTimes=historic)}))))
    assert sum(bool(attempt.unlockedStars[k]) for k in star_keys)==expected
    assert attempt.data.bestLap==min(laps)
# Independent geometry check: every gate must intersect the original racing line
# in the intended direction and within its radius.
line=ai_read(base.parent/'ai/fast_lane.ai');next_line=np.roll(line,-1,axis=0)
crossings=[]
for node in race['pathnodes']:
    p=np.array(node['pos']);n=np.array(node['normal'])
    before=(line-p)@n;after=(next_line-p)@n
    idx=np.flatnonzero((before<=0)&(after>0))
    pts=line[idx]+(next_line[idx]-line[idx])*(-before[idx]/(after[idx]-before[idx]))[:,None]
    valid=np.linalg.norm(pts-p,axis=1)<node['radius']
    assert valid.sum()==1,('Gate missing or ambiguous',node['name'])
    crossings.append(int(idx[valid][0]))
offsets=[(x-crossings[0])%len(line) for x in crossings]
assert offsets==sorted(offsets) and len(set(offsets))==18
start=np.array(race['startPositions'][0]['pos']);finish=np.array(race['pathnodes'][0]['pos'])
normal=np.array(race['pathnodes'][0]['normal'])
assert (start-finish)@normal<0
rot=race['startPositions'][0]['rot'];yaw=2*np.arctan2(rot[2],rot[3])
direction=lua.eval('function(t) return quat(t)*vec3(0,1,0) end')(table(rot))
assert np.dot([direction.x,direction.y,direction.z],normal)>.999
for spawn in race['startPositions']:
    # Native startPosition adds 180 degrees; actual vehicle forward is local -Y,
    # as confirmed by the user's in-game test of the previous revision.
    direction=lua.eval('function(t) return (quatFromEuler(0,0,math.pi)*quat(t))*vec3(0,-1,0) end')(table(spawn['rot']))
    p=np.array(spawn['pos']);idx=np.argmin(np.linalg.norm(line-p,axis=1))
    tangent=line[(idx+2)%len(line)]-line[(idx-2)%len(line)];tangent[2]=0;tangent/=np.linalg.norm(tangent)
    assert np.dot([direction.x,direction.y,direction.z],tangent)>.98
nav=json.loads((level/'map.json').read_text())
waypoints={o['name']:o for s in (level/'main/MissionGroup/Navigation/items.level.json').read_text().splitlines() if (o:=json.loads(s))}
assert len(waypoints)>200 and len(nav['segments'])==2
for seg in nav['segments']:
    assert not seg['hiddenInNavi'] and seg['drivability']==1
    for a,b in zip(seg['nodes'],seg['nodes'][1:]):
        assert a in waypoints and b in waypoints and a!=b
        assert np.linalg.norm(np.array(waypoints[a]['position'])-waypoints[b]['position'])<40
assert nav['segments'][0]['nodes'][0]==nav['segments'][0]['nodes'][-1]
# Execute the installed map.json importer block against the generated waypoints.
source=(game/'lua/ge/map.lua').read_text(encoding='utf-8')
block=source.split('  -- load manual road segments',1)[1].split('\nend',1)[0]
lua.globals().navdata=table(nav)
lua.globals().testMapNodes=table({n:dict(pos=o['position'],radius=o['scale'][0],links={}) for n,o in waypoints.items()})
lua.execute('''
path={split=function() return '/levels/st_stctk_ac_port/' end}
getMissionFilename=function() return '/levels/st_stctk_ac_port/main.level.json' end
readFile=function() return '{}' end
json={decode=function() return navdata end}
_updateProgress=nop
log=function(level,tag,message) if level=='E' or level=='W' then error(message) end end
''')
lua.execute('local mapNodes=testMapNodes; local max=math.max; local getEdgeLaneConfig=function() return "+" end; '+block)
for seg in nav['segments']:
    for a,b in zip(seg['nodes'],seg['nodes'][1:]):
        edge=lua.globals().testMapNodes[a].links[b]
        assert edge and edge.drivability==1 and not edge.hiddenInNavi
materials=json.loads((level/'main.materials.json').read_text(encoding='utf-8'))
color_count=0;curbs={}
for name,mat in materials.items():
    if not name.startswith('acst_'):continue
    stage=mat['Stages'][0]
    if not stage.get('baseColorMap') or '/art/textures/' not in stage['baseColorMap']:continue
    file=unpacked/stage['baseColorMap'].lstrip('/');data=file.read_bytes()
    assert file.name.endswith('.color.dds') and data[84:88]==b'DX10'
    assert struct.unpack_from('<I',data,128)[0] in (72,75,78)
    original=file.with_name(file.name.replace('.color.dds','.dds')).read_bytes()
    assert data[148:]==original[128:],('sRGB payload altered',file.name)
    color_count+=1
    if name.endswith(('_KERBCURB','_curb_stc')):
        rgb=np.array(open_texture(file).convert('RGB'))
        assert rgb.max()<=205 and stage['roughnessFactor']==1
        curbs[name]={'encoded_rgb_max':int(rgb.max()),'roughness':1}
assert len(curbs)==2
fence=materials['acst_st_walls_10_thfence01']
assert not fence['castShadows'] and 'normalMap' not in fence['Stages'][0]
summary=dict(result='PASS',game_launched=False,native_lua_parser=True,
    native_mission_init_and_settings=True,closed_ordered_gates=18,
    original_racing_line_crosses_every_gate_in_order=True,lap_range=[1,20],
    standing_and_flying_starts=True,explicit_srgb_materials=color_count,curbs=curbs,
    native_star_boundary_checks=True,star_thresholds_seconds=[80,70,65],
    native_math_start_directions=True,navigation_waypoints=len(waypoints),
    native_navigation_import=True,
    limitation='Engine graphics, mission UI and actual driving require manual testing.')
(base/'output/v1_validation.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
