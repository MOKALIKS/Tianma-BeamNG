"""Convert this unencrypted AC static track to a self-contained BeamNG prototype.

No Blender or game launch is required. Run with Python 3 and tools/lib dependencies.
All generated data is confined to the source folder's _beamng_conversion directory.
"""
import argparse
import configparser
import csv
import hashlib
import json
import math
import re
import shutil
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent / 'lib'))
import numpy as np
from PIL import Image, ImageDraw
from kn5_reader import load_kn5
from package_mod import package_mod
from texture_compat import normalize_texture
from visual_revision import prepare_surfaces,lift_curb,asphalt_material,native_trees,tree_instances,explicit_opacity,skid_material,finish_pbr_color
from time_trial import build_time_trial

LEVEL = 'st_stctk_ac_port'
NS = 'http://www.collada.org/2005/11/COLLADASchema'
ET.register_namespace('', NS)
IDENTITY = [1, 0, 0, 0, 1, 0, 0, 0, 1]
# Row-vector transform: AC (X,Y-up,Z) -> BeamNG (X,-Z,Y-up).
C = np.array([[1., 0., 0.], [0., 0., 1.], [0., -1., 0.]])


def json_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def lines_write(path, objects):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(o, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n'
                            for o in objects), encoding='utf-8')


def safe(text):
    return re.sub('[^A-Za-z0-9_]', '_', text).strip('_')[:70] or 'asset'


def elem(parent, tag, attrib=None, text=None):
    child = ET.SubElement(parent, '{' + NS + '}' + tag, attrib or {})
    child.text = text
    return child


def floats(array):
    return ' '.join('%.8g' % x for x in np.asarray(array).ravel())


def dae_write(path, mesh_name, material, points, normals, uv, triangles, texture_rel=None):
    root = ET.Element('{' + NS + '}COLLADA', version='1.4.1')
    asset = elem(root, 'asset')
    contributor = elem(asset, 'contributor')
    elem(contributor, 'authoring_tool', text='AC static track prototype converter')
    elem(asset, 'created', text='2026-10-29T00:00:00Z')
    elem(asset, 'modified', text='2026-10-29T00:00:00Z')
    elem(asset, 'unit', {'name':'meter', 'meter':'1'})
    elem(asset, 'up_axis', text='Z_UP')
    if texture_rel:
        images = elem(root, 'library_images')
        im = elem(images, 'image', {'id':'image0', 'name':'image0'})
        elem(im, 'init_from', text=texture_rel)
    effects = elem(root, 'library_effects')
    effect = elem(effects, 'effect', {'id':'effect0'})
    profile = elem(effect, 'profile_COMMON')
    if texture_rel:
        param = elem(profile, 'newparam', {'sid':'image0-surface'})
        elem(elem(param, 'surface', {'type':'2D'}), 'init_from', text='image0')
        param = elem(profile, 'newparam', {'sid':'image0-sampler'})
        elem(elem(param, 'sampler2D'), 'source', text='image0-surface')
    lambert = elem(elem(profile, 'technique', {'sid':'common'}), 'lambert')
    diffuse = elem(lambert, 'diffuse')
    if texture_rel:
        elem(diffuse, 'texture', {'texture':'image0-sampler', 'texcoord':'UVMap'})
    else:
        elem(diffuse, 'color', text='0.6 0.6 0.6 1')
    mat = elem(elem(root, 'library_materials'), 'material', {'id':material+'-material', 'name':material})
    elem(mat, 'instance_effect', {'url':'#effect0'})
    mesh = elem(elem(elem(root, 'library_geometries'), 'geometry', {'id':'geometry0', 'name':mesh_name}), 'mesh')
    for suffix, array, parameters in [('positions',points,'XYZ'), ('normals',normals,'XYZ'), ('uv',uv,'ST')]:
        source = elem(mesh, 'source', {'id':'geometry0-'+suffix})
        elem(source, 'float_array', {'id':'geometry0-'+suffix+'-array', 'count':str(array.size)}, floats(array))
        accessor = elem(elem(source, 'technique_common'), 'accessor',
                        {'source':'#geometry0-'+suffix+'-array','count':str(len(array)),'stride':str(array.shape[1])})
        for p in parameters:
            elem(accessor, 'param', {'name':p,'type':'float'})
    vertex = elem(mesh, 'vertices', {'id':'geometry0-vertices'})
    elem(vertex, 'input', {'semantic':'POSITION','source':'#geometry0-positions'})
    tris = elem(mesh, 'triangles', {'material':material,'count':str(len(triangles))})
    elem(tris, 'input', {'semantic':'VERTEX','source':'#geometry0-vertices','offset':'0'})
    elem(tris, 'input', {'semantic':'NORMAL','source':'#geometry0-normals','offset':'1'})
    elem(tris, 'input', {'semantic':'TEXCOORD','source':'#geometry0-uv','offset':'2','set':'0'})
    elem(tris, 'p', text=' '.join(str(int(i)) for i in np.repeat(triangles.ravel(), 3)))
    visual = elem(elem(root, 'library_visual_scenes'), 'visual_scene', {'id':'Scene','name':'Scene'})
    # Torque mesh suffix supplies an explicit visible detail level.
    node = elem(visual, 'node', {'id':mesh_name+'_a1','name':mesh_name+'_a1','type':'NODE'})
    elem(node, 'matrix', {'sid':'transform'}, text='1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1')
    instance = elem(node, 'instance_geometry', {'url':'#geometry0'})
    bound = elem(elem(instance, 'bind_material'), 'technique_common')
    bound_mat = elem(bound, 'instance_material', {'symbol':material, 'target':'#'+material+'-material'})
    elem(bound_mat, 'bind_vertex_input', {'semantic':'UVMap','input_semantic':'TEXCOORD','input_set':'0'})
    elem(elem(root, 'scene'), 'instance_visual_scene', {'url':'#Scene'})
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def get_ground(name):
    s = name.lower()
    if 'grass' in s: return 'GRASS'
    if 'sand' in s or 'gravel' in s: return 'SAND'
    if 'road' in s or 'asph' in s or 'tarmac' in s: return 'ASPHALT'
    if 'stone' in s or 'rock' in s: return 'ROCK'
    return 'CONCRETE'


def collision_for(file, mesh, mat):
    s = (mesh['name']+' '+mat['name']+' '+mat['shader']).lower()
    if file in ('st_trees', 'st_horizontal', 'st_stcgrooverad'): return False
    if any(token in s for token in ('groove','roadline','roadyan','startline','starline','grassfix',
                                    'grassfx','grasfx','water','banner','flag','sky','lighton')): return False
    if mat['shader'].lower() in ('kstree','ksgrass','ksflags'): return False
    return True


def material_convert(model_stem, index, mat, textures, level_root, warnings):
    name = 'acst_'+model_stem+'_'+str(index)+'_'+safe(mat['name'])
    stage = {'baseColorFactor':[1,1,1,1], 'roughnessFactor':0.85, 'metallicFactor':0,
             'useAnisotropic':True}
    def resource(slot):
        ref = mat['resources'].get(slot)
        if not ref: return None
        output = textures.get(ref['texture'].lower())
        if not output:
            warnings.append(f'{model_stem}/{mat["name"]}: missing texture {ref["texture"]}')
            return None
        return '/levels/'+LEVEL+'/art/textures/'+output
    base = resource('txDiffuse')
    if base: stage['baseColorMap'] = base
    normal = resource('txNormal')
    if normal: stage['normalMap'] = normal
    detail_slot = 'txDetailR' if 'txDetailR' in mat['resources'] else 'txDetail'
    detail = resource(detail_slot)
    mult = mat['props'].get('detailUVMultiplier', [1])[0]
    if detail and mult > 0:
        stage.update(detailMap=detail, detailScale=[float(mult),float(mult)])
    if mat['shader'].startswith('ksMultilayer'):
        warnings.append(f'{model_stem}/{mat["name"]}: multilayer masks approximated with base+one detail layer')
        detail_normal = resource('txDetailNM')
        if detail_normal: stage['detailNormalMap'] = detail_normal
    output = {'name':name,'mapTo':name,'class':'Material','version':1.5,'Stages':[stage],
              'doubleSided':True,'groundType':get_ground(mat['name']), 'translucentBlendOp':'None'}
    # AC *_AT shaders encode cutout in the shader even when the separate flag is 0.
    cutout = bool(mat['alpha_test'] or 'AT' in mat['shader'] or mat['shader'] in ('ksTree','ksGrass','ksFlags'))
    if cutout:
        alpha = mat['props'].get('ksAlphaRef',[0.5])[0]
        output.update(alphaTest=True, alphaRef=max(1,min(254,round((alpha if alpha>0 else 0.05)*255))),
                      castShadows=False if 'groove' in model_stem or mat['name'] in ('roadline','roadyans','grassfix','startline') else True)
    elif mat['blend'] or mat['shader'] == 'ksWindscreen':
        output.update(translucent=True,translucentBlendOp='LerpAlpha',translucentZWrite=True,castShadows=False)
    return name, output, base


def transform_mesh(m):
    matrix = m['matrix']
    p = (m['vertices'][:,:3].astype(np.float64) @ matrix[:3,:3] + matrix[3,:3]) @ C
    n = m['vertices'][:,3:6].astype(np.float64) @ np.linalg.inv(matrix[:3,:3]).T @ C
    n /= np.maximum(np.linalg.norm(n,axis=1,keepdims=True), 1e-15)
    uv = m['vertices'][:,6:8].copy()
    uv[:,1] = 1.0 - uv[:,1]
    triangles = m['indices'].astype(np.int32).copy()
    cross = np.cross(p[triangles[:,1]]-p[triangles[:,0]],p[triangles[:,2]]-p[triangles[:,0]])
    area = np.linalg.norm(cross,axis=1)
    valid = area > 1e-10
    dot = np.einsum('ij,ij->i',cross,n[triangles].sum(axis=1))
    # Detect source winding against source normals rather than assume a handedness.
    flipped = bool(dot[valid].sum() < 0)
    if flipped: triangles = triangles[:,[0,2,1]]
    removed = int((~valid).sum())
    return p, n, uv, triangles[valid], flipped, removed


def height_at(triangles, x, y):
    if len(triangles)==0: return None
    a,b,c = triangles[:,0],triangles[:,1],triangles[:,2]
    v0,v1 = b[:,:2]-a[:,:2],c[:,:2]-a[:,:2]
    v2 = np.array([x,y])-a[:,:2]
    den = v0[:,0]*v1[:,1]-v1[:,0]*v0[:,1]
    good = abs(den)>1e-10
    u = np.zeros(len(a)); v=np.zeros(len(a))
    u[good]=(v2[good,0]*v1[good,1]-v1[good,0]*v2[good,1])/den[good]
    v[good]=(v0[good,0]*v2[good,1]-v2[good,0]*v0[good,1])/den[good]
    good &= (u>=-1e-6)&(v>=-1e-6)&(u+v<=1.000001)
    if not good.any(): return None
    z=a[:,2]+u*(b[:,2]-a[:,2])+v*(c[:,2]-a[:,2])
    return float(z[good].max())


def ai_read(path):
    data=path.read_bytes()
    version,count,_,_=struct.unpack_from('<4i',data)
    if version!=7 or count<2 or len(data)<16+count*20: raise ValueError('Unsupported AC AI layout')
    points=np.array([struct.unpack_from('<3f',data,16+i*20) for i in range(count)])
    return points @ C


def preview_make(source, level_root, triangles, spawns):
    image = Image.open(source/'ui/preview.png').convert('RGB')
    image.save(level_root/'preview.jpg', quality=93)
    # Offline geometry overview provides a quick scale and placement check.
    canvas=Image.new('RGB',(1400,1100),(25,30,36)); draw=ImageDraw.Draw(canvas)
    allp=np.concatenate([p for p,_,_ in triangles])
    low=allp[:,:2].min(axis=0); high=allp[:,:2].max(axis=0)
    scale=min(1260/(high[0]-low[0]),920/(high[1]-low[1]))
    def project(p): return (float(70+(p[0]-low[0])*scale),float(1010-(p[1]-low[1])*scale))
    colors={'ASPHALT':(85,92,102),'GRASS':(65,96,55),'SAND':(164,151,113),'CONCRETE':(128,130,135),'ROCK':(110,105,98)}
    for p,t,g in triangles:
        for face in t:
            draw.polygon([project(v) for v in p[face]], fill=colors[g])
    for spawn in spawns:
        x,y=project(spawn['position']); draw.ellipse((x-4,y-4,x+4,y+4),fill=(255,92,58))
    draw.text((45,25),'ST SHANGHAI TIANMA | OFFLINE GEOMETRY OVERVIEW', fill='white')
    draw.text((45,48),'Converted mesh footprint; red = spawn points. No in-game rendering or driving test.',fill=(195,205,215))
    canvas.save(level_root.parents[2]/'geometry_overview.png')


def convert(source):
    source=source.resolve(); base=source/'_beamng_conversion'
    output=base/'output'; level_root=output/'unpacked/levels'/LEVEL
    shape_root=level_root/'art/shapes'; texture_root=level_root/'art/textures'
    for p in (shape_root,texture_root): p.mkdir(parents=True,exist_ok=True)
    config=configparser.ConfigParser(interpolation=None)
    config.read(source/'models.ini', encoding='utf-8-sig')
    warnings=[]; materials={}; objects=[]; markers=[]; manifest=[]; texture_hashes={}; source_hashes={}
    ground_parts=[]; overview=[]; total_source_triangles=0; skipped_marker_triangles=0; skipped_meshes=0
    texture_conversions=[]
    curb_repairs=[];vegetation=[];tree_counter=0;replaced_tree_groups=[]
    native_materials,tree_models,asset_sources=native_trees(level_root)
    materials.update(native_materials)
    for section in config.sections():
        if not section.startswith('MODEL_'): continue
        spec=config[section]; filename=spec['FILE']
        if Path(filename).name!=filename: raise ValueError('Model path must be local to track folder')
        if any(abs(float(v))>1e-8 for key in ('POSITION','ROTATION') for v in spec.get(key,'0,0,0').split(',')):
            raise ValueError('Nonzero models.ini transforms need an explicit extension to this prototype')
        model=load_kn5(source/filename); stem=Path(filename).stem
        surface_index=prepare_surfaces(model,transform_mesh) if stem=='st_stctk' else None
        source_hashes[filename]=hashlib.sha256((source/filename).read_bytes()).hexdigest()
        markers.extend(model['markers']); texture_map={}
        normal_names={resource['texture'].lower() for mat in model['materials']
                      for slot,resource in mat['resources'].items()
                      if 'normal' in slot.lower() or slot=='txDetailNM'}
        for tex in model['textures']:
            suffix=Path(tex['name'].replace('\\','/')).suffix.lower()
            if suffix not in ('.dds','.png','.jpg','.jpeg','.tga','.bmp'): suffix='.dds'
            key=tex['sha256']
            if key not in texture_hashes:
                tex_name=safe(Path(tex['name'].replace('\\','/')).stem)+'_'+key[:12]+suffix
                texture_data,conversion=normalize_texture(tex['data'],tex['name'],tex['name'].lower() in normal_names)
                if conversion:
                    old=texture_root/tex_name
                    tex_name=Path(tex_name).stem+'_bc3.dds'
                    if old.exists():old.unlink()
                (texture_root/tex_name).write_bytes(texture_data); texture_hashes[key]=tex_name
                if conversion:
                    conversion['output_file']=tex_name
                    texture_conversions.append(conversion)
            texture_map[tex['name'].lower()]=texture_hashes[key]
        mat_refs=[]
        for i,mat in enumerate(model['materials']):
            name,converted,diffuse=material_convert(stem,i,mat,texture_map,level_root,warnings)
            if asphalt_material(mat,converted,texture_root,texture_map):
                diffuse=converted['Stages'][0]['baseColorMap']
            if stem=='st_stcgrooverad' and skid_material(mat,converted,texture_root,texture_map):
                diffuse=converted['Stages'][0]['baseColorMap']
            if mat['name']=='KERBCURB':
                converted['Stages'][0].pop('detailMap',None)
                converted['Stages'][0].pop('detailScale',None)
            explicit_opacity(converted,texture_root)
            finish_pbr_color(mat,converted,texture_root)
            if mat['name']=='thfence01':
                # Fine alpha-tested wire shadows shimmer as shadow cascades move.
                # Keep fence visibility/collision; omit only its thin wire shadow.
                converted['castShadows']=False
                converted['Stages'][0].pop('normalMap',None)
                converted['Stages'][0]['roughnessFactor']=1
            diffuse=converted['Stages'][0].get('baseColorMap',diffuse)
            materials[name]=converted; mat_refs.append((name,diffuse))
        for index,m in enumerate(model['meshes']):
            total_source_triangles+=len(m['indices'])
            if m['name'].startswith('AC_'):
                skipped_marker_triangles+=len(m['indices']); continue
            if not m['active'] or not m['visible'] or not m['renderable']:
                skipped_meshes+=1
                warnings.append(f'{stem}/{m["name"]}: inactive/nonvisible/nonrenderable mesh excluded; check collision if needed')
                continue
            p,n,uv,t,flipped,removed=transform_mesh(m)
            if not len(t): continue
            mat=model['materials'][m['material']]
            duplicate_faces_removed=0
            if stem=='st_walls' and mat['name'] in ('grails01','thfence01','METALGOUEH'):
                # AC contains coincident front/back faces; BeamNG material already
                # draws both sides, so those copies compete in the depth buffer.
                faces=np.round(p[t]*10000).astype(np.int64)
                keys=np.array([f[np.lexsort((f[:,2],f[:,1],f[:,0]))] for f in faces]).reshape(-1,9)
                _,keep=np.unique(keys,axis=0,return_index=True)
                duplicate_faces_removed=len(t)-len(keep);t=t[np.sort(keep)]
            if stem=='st_trees' and mat['shader']=='ksTree':
                replacements,tree_counter=tree_instances(m,p,tree_models,tree_counter)
                vegetation.extend(replacements);replaced_tree_groups.append(m['name'])
                # Remove only this converter's obsolete shape from previous runs.
                old=shape_root/stem/f'{stem}_{index:03d}_{safe(m["name"])}.dae'
                if old.exists():old.unlink()
                continue
            if surface_index and mat['name'] in ('KERBCURB','curb_stc'):
                p,repair=lift_curb(p,t,surface_index,mat['name'],m['name'])
                curb_repairs.append(repair)
            if mat['name'] in ('roadmain','surfaceroad'):
                # World-space four-metre tiles cover every road vertex, with no
                # dependence on AC's lane-wide multilayer mixing mask.
                uv=p[:,:2].copy()/4.0
            center=(p.min(axis=0)+p.max(axis=0))*0.5
            material,diffuse=mat_refs[m['material']]
            name=f'{stem}_{index:03d}_{safe(m["name"])}'
            if stem=='st_stctk' and mat['name'] in ('KERBCURB','curb_stc','roadmain','surfaceroad'):
                old=shape_root/stem/(name+'.dae')
                if old.exists():old.unlink()
                name+='_r4'
            relative=(Path(stem)/(name+'.dae')).as_posix()
            destination=shape_root/relative; destination.parent.mkdir(parents=True,exist_ok=True)
            diffuse_relative=('../../textures/'+Path(diffuse).name) if diffuse else None
            dae_write(destination,name,material,p-center,n,uv,t,diffuse_relative)
            collision=collision_for(stem,m,mat)
            objects.append(dict(name=name, **{'class':'TSStatic','__parent':'TrackMeshes'},
                                position=center.tolist(),rotationMatrix=IDENTITY,scale=[1,1,1],
                                shapeName='/levels/'+LEVEL+'/art/shapes/'+relative,
                                collisionType='Visible Mesh Final' if collision else 'None',
                                decalType='Visible Mesh Final' if collision else 'None',
                                playAmbient=False, meshCulling=False,
                                castShadows=False if mat['name']=='thfence01' else True))
            ground=get_ground(mat['name'])
            if stem=='st_stctk' and collision:
                ground_parts.append(p[t]); overview.append((p,t,ground))
            manifest.append(dict(source=filename,mesh=m['name'],file=relative,material=material,
                                 vertices=len(p),triangles=len(t),collision=collision,groundType=ground,
                                 winding_reversed=flipped,degenerate_removed=removed,
                                 duplicate_faces_removed=duplicate_faces_removed,
                                 bounds=[p.min(axis=0).tolist(),p.max(axis=0).tolist()]))
        print(f'{filename}: parsed exactly {model["bytes_consumed"]:,} bytes; converted',flush=True)
    if not ground_parts: raise ValueError('No drivable surface geometry found')
    ground_triangles=np.concatenate(ground_parts)
    marker_dict={m['name']:m for m in markers}
    spawns=[]
    for marker_name,spawn_name,title in [('AC_START_0','spawn_default','Starting Grid'),
                                         ('AC_PIT_0','spawn_pits','Pit Lane'),
                                         ('AC_HOTLAP_START_0','spawn_hotlap','Hotlap Start')]:
        m=marker_dict.get(marker_name)
        if not m: continue
        matrix=np.array(m['matrix']); point=matrix[3,:3] @ C
        ground_z=height_at(ground_triangles,point[0],point[1])
        if ground_z is None:
            raise ValueError(f'Spawn marker {marker_name} is not above any converted ground')
        point[2]=ground_z+0.5
        # BeamNG vehicle forward is -Y; AC marker forward is local +Z.
        forward=matrix[2,:3] @ C; forward[2]=0
        forward/=max(np.linalg.norm(forward),1e-15)
        local_y=-forward; local_x=np.cross(local_y,[0,0,1])
        rotation=np.vstack([local_x,local_y,[0,0,1]]).ravel().tolist()
        spawns.append(dict(name=spawn_name, **{'class':'SpawnSphere','__parent':'PlayerDropPoints'},
                           position=point.tolist(),rotationMatrix=rotation,scale=[1,1,1],
                           dataBlock='SpawnSphereMarker',radius=2,autoplaceOnSpawn='0',enabled='1'))
    if not spawns or spawns[0]['name']!='spawn_default': raise ValueError('Missing start spawn')
    lines_write(level_root/'main/items.level.json',[dict(name='MissionGroup',**{'class':'SimGroup'})])
    lines_write(level_root/'main/MissionGroup/items.level.json',
                [dict(name=name,**{'class':'SimGroup','__parent':'MissionGroup'})
                 for name in ('Environment','TrackMeshes','Vegetation','PlayerDropPoints','Navigation')])
    lines_write(level_root/'main/MissionGroup/TrackMeshes/items.level.json',objects)
    lines_write(level_root/'main/MissionGroup/Vegetation/items.level.json',vegetation)
    lines_write(level_root/'main/MissionGroup/PlayerDropPoints/items.level.json',spawns)
    environment=[
        dict(name='theLevelInfo', **{'class':'LevelInfo','__parent':'Environment'},
             gravity=-9.81,visibleDistance=4500,fogDensity=0.000025,fogAtmosphereHeight=500,
             fogColor=[0.74,0.81,0.92,1],canvasClearColor='black',globalEnviromentMap='BNG_Sky_01_cubemap'),
        dict(name='sunsky', **{'class':'ScatterSky','__parent':'Environment'},
             azimuth=225,elevation=50,skyBrightness=40,
             ambientScale=[1,0.98,0.96,1],sunScale=[1,0.96,0.90,1],
             ambientScaleGradientFile='art/sky_gradients/default/gradient_ambient.png',
             sunScaleGradientFile='art/sky_gradients/default/gradient_sunscale.png',
             fogScaleGradientFile='art/sky_gradients/default/gradient_fog.png',
             colorizeGradientFile='art/sky_gradients/default/gradient_colorize.png',
             colorize=[0.22,0.35,0.61,1],fogScale=[0.4,0.67,1,1],
             flareType='BNG_Sunflare_3',flareScale=0.6,mieScattering=0.0006,
             castShadows=True,shadowDistance=500,texSize=2048),
        dict(name='tod', **{'class':'TimeOfDay','__parent':'Environment'},
             axisTilt=23.4,azimuthOverride=225,play=False,startTime=0.10,time=0.10,dayLength=86400),
    ]
    lines_write(level_root/'main/MissionGroup/Environment/items.level.json',environment)
    shutil.copyfile(Path(__file__).parent/'map_exposure.lua',level_root/'mainLevel.lua')
    json_write(level_root/'main.materials.json',materials)
    bounds=np.array([m['bounds'] for m in manifest]); extents=bounds[:,1].max(axis=0)-bounds[:,0].min(axis=0)
    json_write(level_root/'info.json',dict(title='Shanghai Tianma Circuit v1.0',
               description='Shanghai Tianma full circuit with standing/flying-start time trial and adjustable laps. Original AC track: SkytenZ.',
               authors='Original Assetto Corsa track: SkytenZ; BeamNG conversion: MOKALIKS',
               previews=['preview.jpg'],size=[int(math.ceil(extents[0])),int(math.ceil(extents[1]))],
               biome='Racetrack',roads='Asphalt circuit',defaultSpawnPointName='spawn_default',supportsTraffic=False,
               spawnPoints=[dict(objectname=s['name'],translationId=t,preview='preview.jpg') for s,t in
                            zip(spawns,['Starting Grid','Pit Lane','Hotlap Start'])]))
    ai_counts={}
    for ai_name in ('fast_lane','pit_lane'):
        ai_path=source/'ai'/(ai_name+'.ai')
        if ai_path.exists():
            points=ai_read(ai_path); ai_counts[ai_name]=len(points)
            with (base/'work'/(ai_name+'_beamng.csv')).open('w',newline='',encoding='utf-8') as f:
                writer=csv.writer(f); writer.writerow(['x','y','z']); writer.writerows(points)
    preview_make(source,level_root,overview,spawns)
    time_trial=build_time_trial(source,level_root)
    warnings.extend([
        'BeamNG has not been launched. Engine import, visuals, spawn orientation and driving are unverified.',
        'Visible Mesh Final collision is used on structural meshes; no optimized collision mesh or LOD was generated.',
        'AC/CSP shaders, weather, night lights and normal-map conventions are approximations, not an exact port.',
        'Circuit and pit navigation generated from AC AI paths; ambient traffic remains disabled.',
        'Thin fences, tire barriers, painted overlays and seams require in-game collision inspection.',
        'Surface groundType is inferred from material names; AC surfaces.ini friction is not numerically reproduced.',
    ])
    report=dict(level=LEVEL,status='offline_conversion_complete_game_not_launched',
                source_sha256=source_hashes,source_triangles=total_source_triangles,
                output_meshes=len(manifest),output_triangles=sum(m['triangles'] for m in manifest),
                marker_triangles_excluded=skipped_marker_triangles,other_meshes_excluded=skipped_meshes,
                materials=len(materials),textures=len(list(texture_root.iterdir())),texture_conversions=texture_conversions,
                content_revision=6,release_version='1.0',time_trial=time_trial,
                color_space='Explicit DX10 sRGB BC1/2/3 base colors; linear normals and masks',
                exposure_bias_ev=-0.20,curb_repairs=curb_repairs,
                native_tree_models=tree_models,native_asset_sources=asset_sources,
                tree_instances=len(vegetation),replaced_tree_groups=replaced_tree_groups,
                collision_meshes=sum(m['collision'] for m in manifest),spawn_points=spawns,
                ai_polylines_exported=ai_counts,warnings=warnings,meshes=manifest)
    json_write(base/'work/conversion_report.json',report)
    archive=output/(LEVEL+'.zip')
    report.update(package_mod(level_root, archive))
    json_write(base/'work/conversion_report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('meshes','spawn_points','source_sha256','warnings')},indent=2),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('source',type=Path)
    args=parser.parse_args(); convert(args.source)
