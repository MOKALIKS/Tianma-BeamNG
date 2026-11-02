"""Build an ordered BeamNG timeTrial mission from AC timing gates and racing line."""
import json
import math
import shutil
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from kn5_reader import load_kn5
from visual_revision import SurfaceIndex

LEVEL='st_stctk_ac_port'
MISSION=f'gameplay/missions/{LEVEL}/timeTrial/001-full-circuit'


def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def build_time_trial(source,level_root):
    from convert_track import C,transform_mesh,ai_read
    model=load_kn5(source/'st_stctk.kn5')
    markers={m['name']:np.array(m['matrix']) for m in model['markers']}
    roads=[];pits=[]
    for mesh in model['meshes']:
        material=model['materials'][mesh['material']]['name']
        if material not in ('roadmain','surfaceroad'):continue
        p,n,u,t,_,_=transform_mesh(mesh)
        if mesh['name'] in ('1pit_sub001','1pit_sub06'):pits.append(p[t])
        elif material=='roadmain':roads.append(p[t])
    road=SurfaceIndex(np.concatenate(roads));pit=SurfaceIndex(np.concatenate(pits))
    left=markers['AC_TIME_0_L'][3,:3]@C;right=markers['AC_TIME_0_R'][3,:3]@C
    finish=(left+right)/2
    forward=markers['AC_TIME_0_L'][2,:3]@C;forward[2]=0;forward/=np.linalg.norm(forward)
    line=ai_read(source/'ai/fast_lane.ai')
    # Insert the intersection of the original racing line with the official AC
    # start/finish timing plane, then keep the original race direction.
    candidates=[]
    for i in range(len(line)):
        a=line[i];b=line[(i+1)%len(line)];da=(a-finish)@forward;db=(b-finish)@forward
        if da<=0<db:
            q=a+(b-a)*(-da)/(db-da)
            candidates.append((np.linalg.norm(q[:2]-finish[:2]),i,q))
    distance,i,q=min(candidates,key=lambda x:x[0]);assert distance<12
    track=np.vstack([q,line[np.r_[np.arange(i+1,len(line)),np.arange(i+1)]],q])
    keep=np.r_[True,np.linalg.norm(np.diff(track,axis=0),axis=1)>.001]
    track=track[keep];s=np.r_[0,np.cumsum(np.linalg.norm(np.diff(track,axis=0),axis=1))]
    length=float(s[-1])
    def at(distance):
        distance=distance%length
        return np.array([np.interp(distance,s,track[:,a]) for a in range(3)])
    def tangent(distance):
        d=at(distance+6)-at(distance-6);d[2]=0
        return d/np.linalg.norm(d)
    def gate(distance):
        p=at(distance);d=tangent(distance);side=np.array([-d[1],d[0],0])
        # Racing line hugs apexes: center each gate between the actual road edges.
        edges=[]
        for sign in [-1,1]:
            extent=0.
            for k in np.arange(.2,18,.2):
                probe=p+side*k*sign
                if road.height(probe) is None:break
                extent=k
            edges.append(extent)
        assert min(edges)>=0 and sum(edges)>5,(distance,edges)
        center=p+side*(edges[1]-edges[0])/2
        z=road.height(center);assert z is not None
        center[2]=z+.7
        return center,d,min(12.,sum(edges)/2+1.0)
    samples=np.arange(35,length-35,3.)
    def angle(distance):
        a=tangent(distance-10);b=tangent(distance+10)
        return math.acos(float(np.clip(a@b,-1,1)))
    ranked=sorted(((angle(float(d)),float(d)) for d in samples),reverse=True)
    selected=[0.]
    # Put gates at the tight bends first; fill long gaps with straight checkpoints.
    for turn,d in ranked:
        if turn<.22:break
        if all(min(abs(d-x),length-abs(d-x))>=70 for x in selected):selected.append(d)
    selected.sort()
    filled=[]
    for a,b in zip(selected,selected[1:]+[length]):
        filled.append(a)
        divisions=math.ceil((b-a)/150)
        filled.extend(a+(b-a)*j/divisions for j in range(1,divisions))
    nodes=[];gates=[]
    for index,distance in enumerate(filled):
        center,d,radius=gate(distance)
        if index==0:
            center=finish.copy();center[2]=road.height(center)+.7
            d=forward.copy();radius=float(np.linalg.norm(left[:2]-right[:2])/2+1)
        nodes.append(dict(oldId=10+index,name='Start / Finish' if index==0 else f'CP {index:02d}',
                          mode='manual',pos=center.tolist(),normal=d.tolist(),radius=radius,
                          navRadiusScale=1,visible=True,useAsSplit=True,sidePadding=[0,0],
                          recovery=-1,reverseRecovery=-1))
        gates.append(dict(index=index,distance_m=distance,pos=center.tolist(),radius=radius))
    def rotation(d,vehicle_start=False):
        # BeamNG's quaternion-vector product uses the inverse of the usual
        # Hamilton rotation. Align local -Y to the racing direction.
        yaw=math.atan2(float(-d[0]),float(-d[1]))
        # Manual in-game testing confirmed that the vehicle spawn needs the
        # opposite heading to the original marker convention.
        if vehicle_start:yaw+=math.pi
        return [0,0,math.sin(yaw/2),math.cos(yaw/2)]
    start=finish-forward*1.5;start[2]=road.height(start)+.12
    rolling_distance=length-160
    rolling,rolling_d,_=gate(rolling_distance);rolling[2]=road.height(rolling)+.12
    pit_markers=np.array([m[3,:3]@C for name,m in markers.items() if name.startswith('AC_PIT_')])
    pit_center=pit_markers.mean(0);pit_center[2]=pit.height(pit_center)+.25
    race=dict(name='Shanghai Tianma — Full Circuit',description='Full circuit with standing and flying starts, following the original racing line.',
              authors='SkytenZ (original track); MOKALIKS (BeamNG conversion)',date=1793491200,
              defaultLaps=3,difficulty=24,startNode=10,endNode=-1,defaultStartPosition=2,
              reverseStartPosition=-1,rollingStartPosition=3,rollingReverseStartPosition=-1,
              classification=dict(closed=True,branching=False,reversible=False,allowRollingStart=True),
              pathnodes=nodes,segments=[dict(oldId=100+j,name=f'Sector {j+1:02d}',mode='waypoint',
                      **{'from':n['oldId'],'to':nodes[(j+1)%len(nodes)]['oldId']},capsules=[]) for j,n in enumerate(nodes)],
              startPositions=[dict(oldId=2,name='Standing start — grid line',group='start',pos=start.tolist(),rot=rotation(forward,True)),
                              dict(oldId=3,name='Flying start — 160 m run-up',group='rollingStart',pos=rolling.tolist(),rot=rotation(rolling_d,True))],
              pacenotes=[],prefabs=[],forwardPrefabs=[],reversePrefabs=[],simplifyAiPath=False,hideMission=False)
    mission=dict(name='上海天马山 · 全赛道计时赛 / Tianma Full Circuit',author='MOKALIKS',date=1793491200,
                 description='在维修区中段接取。可选静止或飞驰起步、1–20 圈；飞驰起步在起跑线前约 160 米起步，跨线后开始计时。依次通过全部检查点。',
                 missionType='timeTrial',retryBehaviour='infiniteRetries',devMission=False,
                 startCondition={'type':'vehicleDriven'},visibleCondition={'type':'always'},
                 startTrigger=dict(type='coordinates',level=LEVEL,pos=pit_center.tolist(),rot=rotation(forward),radius=5),
                 careerSetup=dict(showInFreeroam=True,showInCareer=False,defaultStarKeys=['lapTime1','lapTime2','lapTime3'],
                                  starsActive={'lapTime1':True,'lapTime2':True,'lapTime3':True},starRewards={},starOutroTexts={}),
                 missionTypeData=dict(closed=True,reversible=False,allowRollingStart=True,canChangeLapAmount=True,
                                      defaultLaps=3,mapPreviewMode='waypoints',allowFlip=False,allowRecover=False,
                                      lapTime1=80,lapTime2=70,lapTime3=65,lapTime4=65,lapTime5=65,
                                      flipLimit=0,recoverLimit=0,flipPenalty=0,recoverPenalty=0,
                                      startScreenText='选择圈数与起步方式；按顺序通过检查点，完成一圈返回起跑线。'),
                 setupModules=dict(environment={'enabled':False},traffic={'enabled':False},
                                   vehicles=dict(enabled=True,includePlayerVehicle=True,prioritizePlayerVehicle=True,
                                                 playerVehicleDiffs={},vehicles=[])))
    # The native scorer evaluates all fields, even stars that are disabled.
    # Missing inactive thresholds previously caused a nil comparison on finish.
    data=mission['missionTypeData']
    data.update(justFinishPenalty=0,dynamicRewardsExponentForLaps=1)
    for medal,seconds in [('bronze',80),('silver',70),('gold',65)]:
        data.update({medal+'Time':seconds,medal+'Time2':seconds*2,medal+'Time3':seconds*3,
                     medal+'1Laps':1,medal+'2Laps':2,medal+'3Laps':3,
                     medal+'TimeTotal':seconds*3,medal+'TimePenalty':0,
                     medal+'DynamicLapTimeBase':0,medal+'DynamicLapTimePerLap':seconds})
    mission['description']+=' 单圈星级：1:20 一星，1:10 两星，1:05 三星；多圈以最佳单圈评定。'
    mission['missionTypeData']['startScreenText']+=' 单圈 ≤1:20 / ≤1:10 / ≤1:05 获得一/二/三星。'
    # Native navigation graph drives both minimap and full-map road rendering.
    # Waypoints add no visible road material and no physical collision surfaces.
    waypoints=[];main_names=[];main_positions=[]
    for j,distance in enumerate(np.arange(0,length,8.)):
        p,_,radius=gate(float(distance));p[2]-=.7
        name=f'tianma_nav_{j:04d}';main_names.append(name);main_positions.append(p)
        waypoints.append(dict(name=name,**{'class':'BeamNGWaypoint','__parent':'Navigation'},
                              position=p.tolist(),scale=[max(1,radius-1)]*3,excludeFromMap=False))
    segments=[dict(nodes=main_names+[main_names[0]],drivability=1,oneWay=True,autoJunction=False,
                   hiddenInNavi=False,speedLimit=83.33)]
    pit_line=ai_read(source/'ai/pit_lane.ai');pit_names=[]
    last=None
    for p in pit_line:
        z=pit.height(p)
        if z is None or (last is not None and np.linalg.norm(p-last)<8):continue
        p=p.copy();p[2]=z;last=p
        name=f'tianma_pit_{len(pit_names):04d}';pit_names.append(name)
        waypoints.append(dict(name=name,**{'class':'BeamNGWaypoint','__parent':'Navigation'},
                              position=p.tolist(),scale=[2.5]*3,excludeFromMap=False))
    if len(pit_names)>1:
        positions={o['name']:np.array(o['position']) for o in waypoints}
        # This AC pit file contains repeated partial laps. Select the longest
        # continuous pit passage, never join disjoint passages across infield.
        runs=[[]]
        for name in pit_names:
            if runs[-1] and np.linalg.norm(positions[name]-positions[runs[-1][-1]])>40:runs.append([])
            runs[-1].append(name)
        pit_names=max(runs,key=len)
        keep=set(main_names+pit_names)
        waypoints=[o for o in waypoints if o['name'] in keep]
        joins=[main_names[int(np.argmin(np.linalg.norm(np.array(main_positions)-positions[n],axis=1)))] for n in (pit_names[0],pit_names[-1])]
        segments.append(dict(nodes=[joins[0]]+pit_names+[joins[1]],drivability=1,oneWay=True,
                             autoJunction=False,hiddenInNavi=False,speedLimit=16.67))
    from convert_track import lines_write
    lines_write(level_root/'main/MissionGroup/Navigation/items.level.json',waypoints)
    write(level_root/'map.json',dict(segments=segments))
    folder=level_root.parents[1]/MISSION
    write(folder/'info.json',mission);write(folder/'race.race.json',race)
    shutil.copyfile(level_root/'preview.jpg',folder/'preview.jpg')
    # Route plan is also the mission preview: it makes the pickup point discoverable.
    canvas=Image.new('RGB',(1400,1100),(26,32,39));draw=ImageDraw.Draw(canvas)
    lo=track[:,:2].min(0)-25;hi=track[:,:2].max(0)+25
    scale=min(1260/(hi[0]-lo[0]),900/(hi[1]-lo[1]))
    def proj(p):return (70+(p[0]-lo[0])*scale,1000-(p[1]-lo[1])*scale)
    for tris,color in [(roads,(85,94,105)),(pits,(66,75,87))]:
        for triangles in tris:
            for face in triangles:draw.polygon([proj(v) for v in face],fill=color)
    draw.line([proj(p) for p in track],fill=(120,166,200),width=2)
    for node in nodes:
        p=np.array(node['pos']);d=np.array(node['normal']);side=np.array([-d[1],d[0],0])
        color=(255,186,55) if node['oldId']==10 else (80,230,170)
        draw.line([proj(p-side*node['radius']),proj(p+side*node['radius'])],fill=color,width=4)
        x,y=proj(p);draw.text((x+6,y-13),'S/F' if node['oldId']==10 else str(node['oldId']-10),fill='white')
    for p,label,color in [(pit_center,'PIT: mission pickup',(255,100,100)),(rolling,'FLYING START',(190,145,255))]:
        x,y=proj(p);draw.ellipse((x-5,y-5,x+5,y+5),fill=color);draw.text((x+9,y+7),label,fill=color)
    draw.text((40,24),'SHANGHAI TIANMA | FULL CIRCUIT TIME TRIAL',fill='white')
    draw.text((40,48),f'{length:.0f} m | {len(nodes)-1} intermediate checkpoints + start/finish | 1-20 laps',fill=(200,215,225))
    canvas.save(folder/'preview.jpg',quality=92)
    canvas.save(level_root.parents[2]/'time_trial_route.png')
    result=dict(track_length_m=length,checkpoint_count=len(nodes),intermediate_checkpoints=len(nodes)-1,
                max_gap_m=max(b-a for a,b in zip(filled,filled[1:]+[length])),gates=gates,
                pickup=pit_center.tolist(),standing_start=start.tolist(),rolling_start=rolling.tolist(),
                rolling_runup_m=160,lap_range=[1,20],default_laps=3,mission_path=MISSION,
                timing_gate_source=['AC_TIME_0_L','AC_TIME_0_R'])
    result.update(navigation_waypoints=len(waypoints),navigation_segments=len(segments),star_lap_seconds=[80,70,65])
    write(level_root.parents[2]/'time_trial_report.json',result)
    return result
