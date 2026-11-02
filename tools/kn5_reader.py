"""Strict KN5 v5/v6 static track reader. Original implementation; see references.txt."""
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'lib'))
import numpy as np


class Reader:
    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        self.pos = 0

    def read(self, size):
        end = self.pos + size
        if size < 0 or end > len(self.data):
            raise ValueError(f'{self.path.name}: truncated at {self.pos}, requesting {size}')
        result = self.data[self.pos:end]
        self.pos = end
        return result

    def unpack(self, fmt):
        return struct.unpack('<' + fmt, self.read(struct.calcsize('<' + fmt)))

    def u32(self):
        return self.unpack('I')[0]

    def string(self):
        size = self.u32()
        if size > 1024 * 1024:
            raise ValueError(f'Invalid string length {size} at {self.pos}')
        return self.read(size).decode('utf-8', errors='strict')


def load_kn5(path):
    r = Reader(path)
    if r.read(6) != b'sc6969':
        raise ValueError('Not an ordinary KN5; no protected-resource bypass is implemented')
    version = r.u32()
    if version not in (5, 6):
        raise ValueError(f'Unsupported KN5 version {version}')
    key = r.u32() if version > 5 else None
    textures = []
    for _ in range(r.u32()):
        state = r.u32()
        name = r.string()
        data = r.read(r.u32())
        textures.append(dict(name=name, state=state, data=data, sha256=hashlib.sha256(data).hexdigest()))
    materials = []
    for _ in range(r.u32()):
        name, shader = r.string(), r.string()
        blend, alpha_test = r.unpack('BB')
        depth = r.u32()
        props = {}
        for _ in range(r.u32()):
            prop = r.string()
            props[prop] = list(r.unpack('10f'))
        resources = {}
        for _ in range(r.u32()):
            resource, slot, texture = r.string(), r.u32(), r.string()
            resources[resource] = dict(slot=slot, texture=texture)
        materials.append(dict(name=name, shader=shader, blend=blend, alpha_test=alpha_test,
                              depth=depth, props=props, resources=resources))
    meshes, markers = [], []
    node_count = 0

    def node(parent, parent_active=True, depth=0):
        nonlocal node_count
        if depth > 256:
            raise ValueError('Node nesting limit exceeded')
        kind, name, children, active = r.u32(), r.string(), r.u32(), r.unpack('B')[0]
        node_count += 1
        active = bool(active and parent_active)
        world = parent
        if kind == 1:
            local = np.array(r.unpack('16f'), dtype=np.float64).reshape(4, 4)
            world = local @ parent
            if name.startswith('AC_'):
                markers.append(dict(name=name, matrix=world.tolist(), active=active))
        elif kind in (2, 3):
            cast_shadow, visible, transparent = r.unpack('BBB')
            if kind == 3:
                raise ValueError(f'Skinned mesh {name}: static-track conversion only')
            count = r.u32()
            vertices = np.frombuffer(r.read(count * 44), dtype='<f4').reshape(count, 11).copy()
            indices = np.frombuffer(r.read(r.u32() * 2), dtype='<u2').copy()
            mat, layer = r.unpack('II')
            lod_in, lod_out = r.unpack('ff')
            sphere = r.unpack('4f')
            renderable = r.unpack('B')[0]
            if mat >= len(materials) or len(indices) % 3 or (len(indices) and indices.max() >= count):
                raise ValueError(f'Invalid geometry or material in {name}')
            if not np.isfinite(vertices).all() or not np.isfinite(world).all():
                raise ValueError(f'Non-finite vertex or transform in {name}')
            meshes.append(dict(name=name, vertices=vertices, indices=indices.reshape(-1, 3),
                               material=mat, matrix=world.copy(), active=active,
                               visible=bool(visible), renderable=bool(renderable),
                               cast_shadow=bool(cast_shadow), transparent=bool(transparent),
                               layer=layer, lod_in=lod_in, lod_out=lod_out, sphere=sphere))
        else:
            raise ValueError(f'Unknown node type {kind} at {r.pos}')
        for _ in range(children):
            node(world, active, depth + 1)

    node(np.eye(4))
    if r.pos != len(r.data):
        raise ValueError(f'{Path(path).name}: {len(r.data)-r.pos} bytes left after root node')
    return dict(path=str(path), version=version, key=key, textures=textures,
                materials=materials, meshes=meshes, markers=markers, node_count=node_count,
                bytes_consumed=r.pos)


if __name__ == '__main__':
    import json
    root = Path(sys.argv[1])
    output = []
    for path in sorted(root.glob('*.kn5')):
        model = load_kn5(path)
        bounds = []
        mesh_info = []
        for m in model['meshes']:
            p = m['vertices'][:, :3] @ m['matrix'][:3, :3] + m['matrix'][3, :3]
            if len(p):
                bounds.append([p.min(axis=0).tolist(), p.max(axis=0).tolist()])
            mesh_info.append({k:v for k,v in m.items() if k not in ('vertices','indices','matrix')})
            mesh_info[-1].update(vertices=len(p), triangles=len(m['indices']))
        entry = dict(file=path.name, version=model['version'], bytes_consumed=model['bytes_consumed'],
                     textures=[{k:v for k,v in t.items() if k!='data'} for t in model['textures']],
                     materials=model['materials'], markers=model['markers'], meshes=mesh_info,
                     bounds_ac=[np.min(np.array(bounds)[:, 0],axis=0).tolist(),
                                np.max(np.array(bounds)[:, 1],axis=0).tolist()])
        output.append(entry)
        print(path.name, 'meshes',len(mesh_info),'triangles',sum(x['triangles'] for x in mesh_info),
              'textures',len(model['textures']), 'bytes',model['bytes_consumed'],flush=True)
    (root/'_beamng_conversion/work/inventory.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
