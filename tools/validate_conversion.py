"""Offline checks using independent pycollada and Pillow readers. Never runs BeamNG."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent/'lib'))
import collada
import numpy as np
from PIL import Image
from convert_track import LEVEL, height_at
from texture_compat import check_compatible_dds
from validation_images import open_texture


def check(source):
    source=source.resolve(); base=source/'_beamng_conversion'; output=base/'output'
    unpacked=output/'unpacked'; level=unpacked/'levels'/LEVEL
    report=json.loads((base/'work/conversion_report.json').read_text(encoding='utf-8'))
    materials=json.loads((level/'main.materials.json').read_text(encoding='utf-8'))
    objects=[]
    for p in level.rglob('items.level.json'):
        objects.extend(json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s.strip())
    names=[o['name'] for o in objects]
    assert len(names)==len(set(names)), 'Duplicate scene object names'
    for o in objects:
        assert o.get('__parent','MissionGroup') in names, ('Parent missing',o['name'])
    time_objects=[o for o in objects if o['class']=='TimeOfDay']
    assert len(time_objects)==1, 'Freeroam time progression requires one TimeOfDay object'
    tod=time_objects[0]
    assert 0<=tod['time']<=1 and 0<=tod['startTime']<=1 and tod['dayLength']>0
    by_name={o['name']:o for o in objects}
    cursor=tod; visited=set()
    while cursor['name']!='MissionGroup':
        assert cursor['name'] not in visited, 'Cyclic environment parent'
        visited.add(cursor['name'])
        cursor=by_name[cursor['__parent']]
        assert cursor['class']=='SimGroup'
    native_instances=[o for o in objects if o['class']=='TSStatic' and o.get('__parent')=='Vegetation']
    static={Path(o['shapeName']).name:o for o in objects if o['class']=='TSStatic' and o.get('__parent')!='Vegetation'}
    assert len(static)==report['output_meshes']
    issues=[]
    for name,m in materials.items():
        assert m['name']==name and m['mapTo']==name
        for stage in m['Stages']:
            for key,path in stage.items():
                if key.endswith('Map') and isinstance(path,str):
                    assert path.startswith('/levels/'+LEVEL+'/'), ('External texture',path)
                    assert (unpacked/path.lstrip('/')).is_file(), ('Missing texture',path)
    triangles_total=0; vertex_total=0; ground=[]
    for entry in report['meshes']:
        path=level/'art/shapes'/entry['file']
        assert path.is_file(), ('Missing shape',path)
        obj=static[path.name]
        assert (unpacked/obj['shapeName'].lstrip('/')).resolve()==path.resolve()
        document=collada.Collada(str(path))
        assert not document.errors, (path,document.errors)
        assert document.assetInfo.upaxis=='Z_UP'
        assert len(document.geometries)==1
        primitives=list(document.geometries[0].primitives)
        assert len(primitives)==1
        primitive=primitives[0]
        assert isinstance(primitive,collada.triangleset.TriangleSet)
        assert len(primitive)==entry['triangles']
        assert len(primitive.vertex)==entry['vertices']
        assert primitive.material==entry['material'] and primitive.material in materials
        assert primitive.normal is not None and primitive.texcoordset
        for array in (primitive.vertex, primitive.normal, *primitive.texcoordset):
            assert np.isfinite(array).all(), ('Nonfinite data',path)
        assert primitive.vertex_index.max()<len(primitive.vertex)
        position=np.array(obj['position'])
        world=primitive.vertex.astype(np.float64)+position
        if entry.get('duplicate_faces_removed',0):
            faces=np.round(world[primitive.vertex_index]*10000).astype(np.int64)
            keys=np.array([f[np.lexsort((f[:,2],f[:,1],f[:,0]))] for f in faces]).reshape(-1,9)
            assert len(np.unique(keys,axis=0))==len(keys), ('Fence still has coincident triangles',path)
        bounds=np.array([world.min(axis=0),world.max(axis=0)])
        assert np.allclose(bounds,entry['bounds'],atol=0.0002,rtol=0), ('Position changed',path,bounds,entry['bounds'])
        assert len(list(document.scene.objects('geometry')))==1
        triangles_total+=len(primitive); vertex_total+=len(primitive.vertex)
        if entry['source']=='st_stctk.kn5' and entry['collision']:
            ground.append(world[primitive.vertex_index])
        for image in document.images:
            assert (path.parent/image.path).resolve().is_file(), ('Missing DAE image',image.path)
    assert triangles_total==report['output_triangles']
    ground=np.concatenate(ground)
    spawn_checks=[]
    for s in report['spawn_points']:
        position=s['position']; z=height_at(ground,*position[:2])
        assert z is not None and abs(position[2]-z-0.5)<0.0003, ('Unsupported spawn',s['name'])
        r=np.array(s['rotationMatrix']).reshape(3,3)
        assert np.allclose(r @ r.T,np.eye(3),atol=1e-6) and np.isclose(np.linalg.det(r),1)
        spawn_checks.append(dict(name=s['name'],height_above_mesh_m=position[2]-z))
    texture_formats={}; texture_count=0
    for p in (level/'art/textures').iterdir():
        if p.suffix.lower()=='.dds':
            check_compatible_dds(p.read_bytes())
            if p.stem.endswith('_bc3') or p.stem.endswith('_opacity') or p.stem.startswith(('r4_','r5_')):
                from texture_compat import dds_header
                data=p.read_bytes();h=dds_header(data)
                import struct
                srgb=data[84:88]==b'DX10'
                assert (srgb and struct.unpack_from('<I',data,128)[0]==78) or data[84:88]==b'DXT5'
                assert h[6]==max(h[2],h[3]).bit_length()
                offset=148 if srgb else 128
                assert len(data)==offset+sum(max(1,(max(1,h[3]>>i)+3)//4)*max(1,(max(1,h[2]>>i)+3)//4)*16 for i in range(h[6]))
        with open_texture(p) as im:
            assert im.width>0 and im.height>0
            im.load()  # Decode complete image, not only its header.
            texture_formats[im.format]=texture_formats.get(im.format,0)+1
        texture_count+=1
    assert texture_count==report['textures']
    native_shapes={}
    for key,model in report.get('native_tree_models',{}).items():
        path=unpacked/model['path'].lstrip('/')
        document=collada.Collada(str(path))
        assert not document.errors,(key,document.errors)
        assert document.assetInfo.upaxis=='Z_UP'
        bound=list(document.scene.objects('geometry'))
        assert len(bound)>=2, 'Native vegetation needs multiple distance LODs'
        count=0
        for geo in bound:
            for primitive in geo.primitives():
                assert np.isfinite(primitive.vertex).all()
                assert primitive.material.name in materials, ('Missing native material',key,primitive.material.name)
                count+=len(primitive)
        assert count==model['triangles_all_lods']
        native_shapes[key]=dict(lods=len(bound),triangles_all_lods=count)
    assert len(native_instances)==report.get('tree_instances',0)
    for o in native_instances:
        assert o['shapeName'] in {m['path'] for m in report['native_tree_models'].values()}
        assert np.isfinite(o['position']+o['scale']).all() and min(o['scale'])>0
        r=np.array(o['rotationMatrix']).reshape(3,3)
        assert np.allclose(r@r.T,np.eye(3),atol=1e-6) and np.isclose(np.linalg.det(r),1)
    native_textures=0
    for p in (level/'art/native_trees').rglob('*.dds'):
        with Image.open(p) as im: im.load()
        native_textures+=1
    for name,mat in materials.items():
        if name.endswith('_roadmain') or name.endswith('_surfaceroad'):
            assert mat['groundType']=='ASPHALT' and not mat.get('alphaTest') and not mat.get('translucent')
            with open_texture(unpacked/mat['Stages'][0]['baseColorMap'].lstrip('/')) as im:
                assert np.array(im.convert('RGBA'))[:,:,3].min()==255
    assert all(c['minimum_clearance_after_m']>=.0079 for c in report.get('curb_repairs',[]))
    source_unchanged={}
    for name,expected in report['source_sha256'].items():
        digest=hashlib.sha256((source/name).read_bytes()).hexdigest()
        assert digest==expected, ('Source changed',name)
        source_unchanged[name]=True
    archive=output/(LEVEL+'.zip')
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None, 'ZIP CRC error'
        zip_entries=z.infolist()
        zip_files=[i.filename for i in zip_entries if not i.is_dir()]
        zip_directories=[i.filename for i in zip_entries if i.is_dir()]
        mission_root=unpacked/'gameplay/missions'/LEVEL
        disk_files=[p for root in (level,mission_root) for p in root.rglob('*') if p.is_file()]
        assert len(zip_files)==len(disk_files)
        assert all(n.startswith(('levels/'+LEVEL+'/','gameplay/missions/'+LEVEL+'/')) and '..' not in n.split('/') for n in zip_files)
        assert 'levels/' in zip_directories and 'levels/'+LEVEL+'/main/' in zip_directories
        assert all(i.extract_version<=20 and not i.extra and i.flag_bits & 1==0 for i in zip_entries)
        assert all(i.create_system==0 and i.external_attr==(0x10 if i.is_dir() else 0x20) for i in zip_entries)
        for p in disk_files:
            assert z.read(p.relative_to(unpacked).as_posix())==p.read_bytes(), ('ZIP contents stale',p)
    summary=dict(result='PASS',validation='offline_only_no_game_launch',
                 independent_mesh_reader='pycollada',mesh_files=report['output_meshes'],
                 triangles=triangles_total,vertices=vertex_total,
                 materials=len(materials),decoded_textures=texture_count,texture_formats=texture_formats,
                 scene_objects=len(objects),time_of_day_object=tod['name'],
                 native_tree_instances=len(native_instances),native_tree_shapes=native_shapes,
                 native_tree_textures_decoded=native_textures,
                 dds_runtime_constraints_checked=True,spawn_checks=spawn_checks,
                 source_kn5_unchanged=source_unchanged,zip_entries=len(zip_entries),
                 zip_files=len(zip_files),zip_directories=len(zip_directories),
                 zip_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                 game_import_verified=False,visuals_verified=False,driving_verified=False)
    (output/'offline_validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    check(Path(sys.argv[1]))
