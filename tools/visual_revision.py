"""R4: surface geometry, opaque asphalt, and locally sourced native LOD trees."""
import copy
import hashlib
import io
import json
import math
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from PIL import Image
from texture_compat import save_dxt5,as_srgb_dds

LEVEL='st_stctk_ac_port'
GAME=Path(os.environ['BEAMNG_GAME_ROOT']) if os.environ.get('BEAMNG_GAME_ROOT') else None
NS={'c':'http://www.collada.org/2005/11/COLLADASchema'}


class SurfaceIndex:
    def __init__(self, triangles):
        self.triangles=triangles
        self.cells={}
        for i,t in enumerate(triangles):
            lo=np.floor(t[:,:2].min(0)/10).astype(int)
            hi=np.floor(t[:,:2].max(0)/10).astype(int)
            for x in range(lo[0],hi[0]+1):
                for y in range(lo[1],hi[1]+1):self.cells.setdefault((x,y),[]).append(i)
    def height(self,p):
        from convert_track import height_at
        ids=self.cells.get(tuple(np.floor(np.asarray(p[:2])/10).astype(int)),[])
        return height_at(self.triangles[ids],*p[:2]) if ids else None


def prepare_surfaces(model,transform):
    faces=[]
    for mesh in model['meshes']:
        if model['materials'][mesh['material']]['name'] in ('roadmain','surfaceroad','grass9base','sand'):
            p,n,u,t,_,_=transform(mesh);faces.append(p[t])
    return SurfaceIndex(np.concatenate(faces))


def lift_curb(p,t,index,mat,mesh_name):
    # Include edge midpoints and triangle centers; the source surfaces actually
    # intersect, so a material depth bias alone would not fix wheel collisions.
    faces=p[t]
    probes=np.concatenate([p,faces.mean(1),(faces[:,0]+faces[:,1])/2,
                           (faces[:,1]+faces[:,2])/2,(faces[:,2]+faces[:,0])/2])
    heights=[(v[2]-h) for v in probes if (h:=index.height(v)) is not None]
    minimum=min(heights) if heights else 0.
    clearance=.008 if mat=='curb_stc' else .012
    lift=max(0.,clearance-minimum)
    if lift>.10:raise ValueError(f'Unexpected curb intersection: {mesh_name}, {minimum}')
    p=p.copy();p[:,2]+=lift
    return p,dict(mesh=mesh_name,material=mat,sampled_points=len(heights),
                  minimum_clearance_before_m=minimum,lift_m=lift,
                  minimum_clearance_after_m=minimum+lift)


def asphalt_material(mat,converted,texture_root,texture_map):
    if mat['name'] not in ('roadmain','surfaceroad'):return False
    # AC txDiffuse alpha is a shader mixing mask, NOT road transparency.
    # Use the original asphalt detail as an opaque, full-width tiled base.
    source=texture_root/texture_map[mat['resources']['txDetailR']['texture'].lower()]
    im=Image.open(source).convert('RGB')
    arr=np.asarray(im,dtype=float)
    luminance=arr.mean(2)
    target=52 if mat['name']=='roadmain' else 61
    # Retain grain but avoid the coarse high-contrast aggregate appearance.
    gray=np.clip(target+(luminance-luminance.mean())*.32,25,100).astype('uint8')
    color=np.stack([gray,gray,np.clip(gray.astype(int)+2,0,255).astype('uint8')],axis=2)
    filename='r5_'+mat['name']+'_asphalt.dds'
    old=texture_root/('r4_'+mat['name']+'_asphalt.dds')
    if old.exists():old.unlink()
    save_dxt5(Image.fromarray(color),texture_root/filename)
    converted['Stages']=[dict(baseColorMap=f'/levels/{LEVEL}/art/textures/{filename}',
                             baseColorFactor=[1,1,1,1],roughnessFactor=.93,
                             metallicFactor=0,useAnisotropic=True)]
    converted.update(alphaTest=False,translucent=False,translucentBlendOp='None',
                     doubleSided=False,groundType='ASPHALT')
    return True


def skid_material(mat,converted,texture_root,texture_map):
    if mat['name'] not in ('road_groove','typelimns'):return False
    source=texture_root/texture_map[mat['resources']['txDiffuse']['texture'].lower()]
    original=Image.open(source).convert('RGBA')
    rgba=np.asarray(original).copy()
    # Alpha describes rubber coverage. The original blue-gray RGB is brighter
    # than the corrected asphalt, so use dark neutral rubber with the same mask.
    gray=np.clip(rgba[:,:,:3].astype(float).mean(2)*.22,8,30).astype('uint8')
    rgba[:,:,:3]=gray[:,:,None]
    filename='r5_'+mat['name']+'_rubber.dds'
    save_dxt5(Image.fromarray(rgba),texture_root/filename)
    converted['Stages']=[dict(baseColorMap=f'/levels/{LEVEL}/art/textures/{filename}',
                             baseColorFactor=[1,1,1,1],roughnessFactor=1,
                             metallicFactor=0,useAnisotropic=True)]
    converted.update(alphaTest=False,alphaRef=0,translucent=True,
                     translucentBlendOp='LerpAlpha',translucentZWrite=False,
                     castShadows=False,groundType='ASPHALT')
    return True


def explicit_opacity(converted,texture_root):
    """PBR opacity has its own texture slot; AC packs it into diffuse alpha."""
    if not (converted.get('alphaTest') or converted.get('translucent')):return
    stage=converted['Stages'][0]
    if not stage.get('baseColorMap'):return
    source=texture_root/Path(stage['baseColorMap']).name
    alpha=Image.open(source).convert('RGBA').getchannel('A')
    if alpha.getextrema()==(255,255):return
    filename=source.stem+'_opacity.dds'
    save_dxt5(alpha.convert('RGB'),texture_root/filename)
    stage['opacityMap']=f'/levels/{LEVEL}/art/textures/{filename}'


def finish_pbr_color(mat,converted,texture_root):
    """AC diffuse maps are sRGB; v1.5 DDS needs an explicit sRGB format."""
    stage=converted['Stages'][0]
    if not stage.get('baseColorMap'):return
    source=texture_root/Path(stage['baseColorMap']).name
    if mat['name'] in ('KERBCURB','curb_stc'):
        rgba=np.array(Image.open(source).convert('RGBA'))
        rgba[:,:,:3]=np.rint(rgba[:,:,:3].astype(float)*.78).astype('uint8')
        source=texture_root/('v1_'+mat['name']+'_paint.dds')
        save_dxt5(Image.fromarray(rgba),source)
        stage['roughnessFactor']=1.0
        stage['normalMapStrength']=.45
    target=source.with_name(source.stem+'.color.dds')
    target.write_bytes(as_srgb_dds(source.read_bytes()))
    stage['baseColorMap']=f'/levels/{LEVEL}/art/textures/{target.name}'


def native_trees(level_root):
    if GAME is None:
        raise RuntimeError('Set BEAMNG_GAME_ROOT to the BeamNG.drive installation directory, or use Build.ps1 -GameRoot.')
    root=level_root/'art/native_trees';root.mkdir(parents=True,exist_ok=True)
    textures=root/'textures';textures.mkdir(exist_ok=True)
    archive=GAME/'content/levels/hirochi_raceway.zip'
    tex_archive=GAME/'content/assets/materials/tree.zip'
    prefix='levels/hirochi_raceway/art/shapes/trees/trees_oak/'
    variants=['tree_oak_sml_a','tree_oak_sml_b','tree_oak_forest_a','tree_oak_bush_a']
    materials={};models={};sources=[];copied={}
    with zipfile.ZipFile(archive) as z,zipfile.ZipFile(tex_archive) as tz:
        originals=json.loads(z.read(prefix+'main.materials.json'))
        for variant in variants:
            source=z.read(prefix+variant+'.dae');doc=ET.fromstring(source)
            # Keep three native distance LODs and the baked far imposter. Collision
            # was disabled on AC vegetation and stays disabled on these instances.
            for parent in doc.iter():
                for child in list(parent):
                    if child.tag.endswith('node') and child.get('name','').startswith('Colmesh'):
                        parent.remove(child)
            used_geometries={e.get('url')[1:] for e in doc.findall('.//c:visual_scene//c:instance_geometry',NS)}
            geolib=doc.find('c:library_geometries',NS)
            for g in list(geolib):
                if g.get('id') not in used_geometries:geolib.remove(g)
            used={e.get('target')[1:] for e in doc.findall('.//c:visual_scene//c:instance_material',NS)}
            lib=doc.find('c:library_materials',NS)
            rename={}
            for material in list(lib):
                if material.get('id') not in used:
                    lib.remove(material);continue
                old=material.get('name');new='acst_native_'+old
                rename[old]=new
                if new not in materials:
                    data=copy.deepcopy(originals[old]);data.pop('persistentId',None)
                    data.update(name=new,mapTo=new)
                    for stage in data['Stages']:
                        # Tiny bark detail is optional and adds unrelated tropical
                        # assets; native base/normal/AO/roughness/opacity are retained.
                        for key in list(stage):
                            if key in ('detailMap','detailNormalMap'):stage.pop(key)
                        for key,value in stage.items():
                            if not key.endswith('Map') or not isinstance(value,str):continue
                            internal=str(Path(value.lstrip('/')).with_suffix('.dds')).replace('\\','/')
                            blob=tz.read(internal)
                            filename=Path(internal).name
                            if filename in copied:assert copied[filename]==hashlib.sha256(blob).hexdigest()
                            else:
                                (textures/filename).write_bytes(blob)
                                copied[filename]=hashlib.sha256(blob).hexdigest()
                                sources.append(dict(archive=str(tex_archive),entry=internal,sha256=copied[filename]))
                            stage[key]=f'/levels/{LEVEL}/art/native_trees/textures/{filename}'
                    materials[new]=data
            # Torque resolves material names. Remove authoring-package image links
            # (some are absolute artist-machine paths) from the fallback effects.
            images=doc.find('c:library_images',NS)
            if images is not None:doc.remove(images)
            effects=doc.find('c:library_effects',NS)
            tag='{'+NS['c']+'}'
            for effect in effects:
                for child in list(effect):effect.remove(child)
                profile=ET.SubElement(effect,tag+'profile_COMMON')
                technique=ET.SubElement(profile,tag+'technique',sid='common')
                diffuse=ET.SubElement(ET.SubElement(technique,tag+'lambert'),tag+'diffuse')
                ET.SubElement(diffuse,tag+'color').text='.3 .4 .2 1'
            for element in doc.iter():
                for key,value in list(element.attrib.items()):
                    for old,new in rename.items():value=re.sub(r'(?<![\w])'+re.escape(old)+r'(?![\w])',new,value)
                    element.set(key,value)
            path=root/(variant+'.dae');ET.ElementTree(doc).write(path,encoding='utf-8',xml_declaration=True)
            for suffix in ['.dae.imposter.dds','.dae.imposter_normals.dds']:
                (root/(variant+suffix)).write_bytes(z.read(prefix+variant+suffix))
            points=[];triangles=0
            for g in geolib:
                for source_node in g.findall('c:mesh/c:source',NS):
                    if 'positions' in source_node.get('id',''):
                        points.append(np.fromstring(source_node.find('c:float_array',NS).text,sep=' ').reshape(-1,3))
                triangles+=sum(int(e.get('count')) for e in g.findall('c:mesh/c:triangles',NS))
            p=np.concatenate(points);lo=p.min(0);hi=p.max(0)
            models[variant]=dict(path=f'/levels/{LEVEL}/art/native_trees/{variant}.dae',
                                 bounds=[lo.tolist(),hi.tolist()],height=float(hi[2]-lo[2]),
                                 triangles_all_lods=triangles)
            sources.append(dict(archive=str(archive),entry=prefix+variant+'.dae',sha256=hashlib.sha256(source).hexdigest()))
    return materials,models,sources


def tree_instances(mesh,p,models,counter):
    assert len(p)%24==0 and len(mesh['indices'])==len(p)//2
    assert np.all(mesh['indices']//24==(mesh['indices']//24)[:,0,None]), 'Tree layout changed'
    objects=[]
    for group in p.reshape(-1,24,3):
        # Three radial half-planes, each duplicated on the reverse side. The
        # common vertical edge is the tree's actual trunk location, not AABB center.
        close=np.linalg.norm(group[:,None,:2]-group[None,:,:2],axis=2)<.001
        counts=close.sum(1)
        assert counts.max()>=12
        center=group[close[counts.argmax()],:2].mean(0);height=float(np.ptp(group[:,2]))
        variant='tree_oak_bush_a' if height<4 else (
            'tree_oak_forest_a' if height>22 else ['tree_oak_sml_a','tree_oak_sml_b'][counter%2])
        model=models[variant]
        zscale=height/model['height']
        # Preserve original footprint; tall narrow tree rows must stay narrow.
        source_width=float(np.ptp(group[:,:2],axis=0).max())
        model_width=max(np.subtract(model['bounds'][1],model['bounds'][0])[:2])
        xyscale=min(zscale*1.15,source_width/model_width)
        angle=(counter*2.399963229728653)%math.tau;c=math.cos(angle);s=math.sin(angle)
        objects.append(dict(name=f'acst_tree_{counter:04d}',**{'class':'TSStatic','__parent':'Vegetation'},
                            position=[float(center[0]),float(center[1]),float(group[:,2].min()-model['bounds'][0][2]*zscale)],
                            rotationMatrix=[c,s,0,-s,c,0,0,0,1],scale=[xyscale,xyscale,zscale],
                            shapeName=model['path'],collisionType='None',decalType='None',
                            playAmbient=False,meshCulling=True,castShadows=True))
        counter+=1
    return objects,counter
