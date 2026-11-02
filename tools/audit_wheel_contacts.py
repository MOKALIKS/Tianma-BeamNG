"""Inspect sampled wheel contact heights and identify meshes above the road."""
import json
import sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).parent/'lib'))
import numpy as np
import collada
from convert_track import ai_read
from visual_revision import SurfaceIndex
base=Path(__file__).resolve().parents[1];level=base/'output/unpacked/levels/st_stctk_ac_port'
r=json.loads((base/'work/conversion_report.json').read_text(encoding='utf-8'))
objects={o['shapeName'].split('/art/shapes/')[-1]:o for s in (level/'main/MissionGroup/TrackMeshes/items.level.json').read_text().splitlines() if (o:=json.loads(s))}
faces=[];labels=[];road=[]
for e in r['meshes']:
    if not e['collision']:continue
    d=collada.Collada(str(level/'art/shapes'/e['file']));p=d.geometries[0].primitives[0]
    t=p.vertex[p.vertex_index].astype(float)+objects[e['file']]['position']
    faces.append(t);labels.extend([e['mesh']+' / '+e['material']]*len(t))
    if e['material'].endswith(('_roadmain','_surfaceroad')):road.append(t)
faces=np.concatenate(faces);index=SurfaceIndex(faces);road=np.concatenate(road);road_index=SurfaceIndex(road)
line=ai_read(base.parent/'ai/fast_lane.ai');direction=np.roll(line,-1,axis=0)-np.roll(line,1,axis=0)
direction[:,2]=0;direction/=np.linalg.norm(direction,axis=1)[:,None]
side=np.column_stack([-direction[:,1],direction[:,0],np.zeros(len(line))])
results={}
for offset in [-.85,0,.85]:
    missing=0;obstacles={};heights=[];largest=None
    for i,p in enumerate(line+side*offset):
        ids=np.array(index.cells.get(tuple(np.floor(p[:2]/10).astype(int)),[]),dtype=int)
        t=faces[ids];a,b,c=t[:,0],t[:,1],t[:,2]
        v0=b[:,:2]-a[:,:2];v1=c[:,:2]-a[:,:2];v2=p[:2]-a[:,:2]
        den=v0[:,0]*v1[:,1]-v1[:,0]*v0[:,1];valid=abs(den)>1e-10
        u=np.zeros(len(t));v=u.copy()
        u[valid]=(v2[valid,0]*v1[valid,1]-v1[valid,0]*v2[valid,1])/den[valid]
        v[valid]=(v0[valid,0]*v2[valid,1]-v2[valid,0]*v0[valid,1])/den[valid]
        z=a[:,2]+u*(b[:,2]-a[:,2])+v*(c[:,2]-a[:,2])
        valid&=(u>=-1e-6)&(v>=-1e-6)&(u+v<=1.000001)&(z<p[2]+1)&(z>p[2]-1)
        if not valid.any():missing+=1;heights.append(np.nan);continue
        local=np.flatnonzero(valid)[np.argmax(z[valid])];h=z[local];heights.append(h)
        rz=road_index.height(p)
        if rz is not None and h-rz>.025:
            label=labels[ids[local]];obstacles[label]=obstacles.get(label,0)+1
            if largest is None or h-rz>largest['height_above_road_m']:
                largest=dict(mesh=label,pos=p.tolist(),height_above_road_m=float(h-rz))
    heights=np.array(heights)
    spacing=np.linalg.norm(np.roll(line,-1,axis=0)[:,:2]-line[:,:2],axis=1)
    jumps=abs(np.roll(heights,-1)-heights)
    results[str(offset)]=dict(samples=len(line),missing_collision_within_1m=missing,
        max_sample_height_change_m=float(np.nanmax(jumps)),max_sample_spacing_m=float(spacing.max()),
        above_road_meshes=obstacles,largest=largest)
# Compare shared road edge endpoints in XY to reveal vertical cracks between faces.
edge_heights={}
for t in road:
    for a,b in ((t[0],t[1]),(t[1],t[2]),(t[2],t[0])):
        if tuple(a[:2])>tuple(b[:2]):a,b=b,a
        key=tuple(np.round(np.r_[a[:2],b[:2]]*1000).astype(int))
        edge_heights.setdefault(key,[]).append([float(a[2]),float(b[2])])
gaps=[float(np.ptp(np.array(z),axis=0).max()) for z in edge_heights.values() if len(z)>1]
report=dict(wheel_contacts=results,matched_road_edges=len(gaps),max_matched_road_edge_height_gap_m=max(gaps),
    conclusion='No causal tire-failure diagnosis: offline samples only; curb impacts, all driving lines, vehicle configuration and tire damage physics are not simulated.')
(base/'output/wheel_contact_audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
