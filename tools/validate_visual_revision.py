"""Independent R4 world-space surface checks using exported COLLADA files."""
import json
import sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).parent/'lib'))
import collada
import numpy as np
from visual_revision import SurfaceIndex

base=Path(__file__).resolve().parents[1]
level=base/'output/unpacked/levels/st_stctk_ac_port'
report=json.loads((base/'work/conversion_report.json').read_text())
objects={o['name']:o for o in map(json.loads,(level/'main/MissionGroup/TrackMeshes/items.level.json').read_text().splitlines())}
surfaces=[];curbs=[];roads=[]
for entry in report['meshes']:
    if entry['source']!='st_stctk.kn5':continue
    mat=entry['material'].split('_',4)[-1]
    path=level/'art/shapes'/entry['file'];obj=objects[path.stem]
    primitive=collada.Collada(str(path)).geometries[0].primitives[0]
    world=primitive.vertex.astype(float)+np.array(obj['position'])
    triangles=world[primitive.vertex_index]
    if mat in ('roadmain','surfaceroad','grass9base','sand'):surfaces.append(triangles)
    if mat in ('KERBCURB','curb_stc'):curbs.append((entry,triangles))
    if mat in ('roadmain','surfaceroad'):
        assert np.allclose(primitive.texcoordset[0],world[:,:2]/4,atol=1e-4)
        roads.append(entry['mesh'])
index=SurfaceIndex(np.concatenate(surfaces));results=[]
rng=np.random.default_rng(20261029)
for entry,triangles in curbs:
    # Random interior points are independent of the exporter's vertex/edge/
    # centroid probes and catch interpolation penetrations missed by AABBs.
    ids=rng.integers(0,len(triangles),1200)
    weights=rng.dirichlet([1,1,1],len(ids))
    probes=np.einsum('ni,nij->nj',weights,triangles[ids])
    clearances=[p[2]-h for p in probes if (h:=index.height(p)) is not None]
    assert not clearances or min(clearances)>.005,(entry['mesh'],min(clearances))
    results.append(dict(mesh=entry['mesh'],samples=len(clearances),minimum_clearance_m=min(clearances) if clearances else None))
summary=dict(result='PASS',revision=4,road_uv_world_space_verified=roads,
             independent_curb_sampling=results,game_launched=False,visuals_verified=False)
(base/'output/visual_geometry_validation.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
