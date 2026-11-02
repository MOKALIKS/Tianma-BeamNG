"""Offline collision and duplicate-face audit. Does not infer tire failure causality."""
import json
import sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).parent/'lib'))
import numpy as np
import collada
from convert_track import ai_read
from visual_revision import SurfaceIndex
base=Path(__file__).resolve().parents[1]
level=base/'output/unpacked/levels/st_stctk_ac_port'
report=json.loads((base/'work/conversion_report.json').read_text(encoding='utf-8'))
objects={o['shapeName'].split('/art/shapes/')[-1]:o for line in (level/'main/MissionGroup/TrackMeshes/items.level.json').read_text().splitlines() if (o:=json.loads(line))}
road=[];solid=[];duplicates=[];fences=[];mesh_stats=[]
for entry in report['meshes']:
    doc=collada.Collada(str(level/'art/shapes'/entry['file']))
    primitive=doc.geometries[0].primitives[0]
    p=primitive.vertex.astype(float)+objects[entry['file']]['position'];t=p[primitive.vertex_index]
    # Quantize to 0.1 mm and ignore winding to detect opposing coplanar faces.
    q=np.round(t*10000).astype(np.int64)
    ordered=np.array([face[np.lexsort((face[:,2],face[:,1],face[:,0]))] for face in q])
    _,counts=np.unique(ordered.reshape(-1,9),axis=0,return_counts=True)
    duplicate_count=int((counts-1).sum())
    if duplicate_count:duplicates.append(dict(mesh=entry['mesh'],material=entry['material'],collision=entry['collision'],duplicates=duplicate_count))
    if entry['collision']:solid.append(t)
    if entry['material'].endswith(('_roadmain','_surfaceroad')):road.append(t)
    if 'fence' in entry['material'] or 'grails' in entry['material']:fences.append(dict(mesh=entry['mesh'],triangles=len(t),duplicates=duplicate_count))
road_index=SurfaceIndex(np.concatenate(road));solid_index=SurfaceIndex(np.concatenate(solid))
line=ai_read(base.parent/'ai/fast_lane.ai');tangent=np.roll(line,-1,axis=0)-np.roll(line,1,axis=0)
tangent[:,2]=0;tangent/=np.linalg.norm(tangent,axis=1)[:,None]
side=np.column_stack([-tangent[:,1],tangent[:,0],np.zeros(len(line))])
samples={}
for offset in [-.85,0,.85]:
    heights=[];extra=[];missing=0
    for i,p in enumerate(line+side*offset):
        z=road_index.height(p)
        if z is None:missing+=1;heights.append(np.nan);continue
        heights.append(z)
        top=solid_index.height(p)
        if top is not None and top-z>.025:extra.append(dict(index=i,pos=p.tolist(),above_road_m=top-z))
    heights=np.array(heights);jump=np.abs(np.roll(heights,-1)-heights)
    samples[str(offset)]=dict(samples=len(line),missing_road=missing,max_neighbor_height_change_m=float(np.nanmax(jump)),
                              extra_colliders_over_road=extra[:30],extra_colliders_count=len(extra))
summary=dict(duplicate_faces=duplicates,fences=fences,wheel_corridor_samples=samples,
             limitation='Samples racing line and +/-0.85 m wheel tracks. Does not simulate tire damage, every possible line, curb strikes or vehicle setup.')
(base/'output/collision_audit.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
