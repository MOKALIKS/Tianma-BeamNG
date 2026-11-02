"""Normalize DDS variants rejected by BeamNG to legacy DXT5 with full mipmaps."""
import hashlib
import io
import struct
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).parent/'lib'))
import numpy as np
from PIL import Image


def dds_header(data):
    if len(data)<128 or data[:4]!=b'DDS ':
        raise ValueError('Expected a DDS texture')
    h=struct.unpack_from('<31I',data,4)
    if h[0]!=124 or h[18]!=32:
        raise ValueError('Invalid DDS header')
    return h


def normalize_texture(data, name, normal_map=False):
    if not data.startswith(b'DDS '):
        return data,None
    h=dds_header(data)
    width,height=h[3],h[2]
    reasons=[]
    if (width & (width-1)) or (height & (height-1)):
        reasons.append('non_power_of_two_dimensions')
    if h[19]&0x40 and h[21]!=32:
        reasons.append(f'unsupported_uncompressed_rgb{h[21]}')
    if not reasons:
        return data,None
    original=Image.open(io.BytesIO(data)).convert('RGBA')
    target=(1<<(width-1).bit_length(),1<<(height-1).bit_length())
    current=original.resize(target,Image.Resampling.LANCZOS) if original.size!=target else original
    mip_images=[]
    while True:
        mip_images.append(current)
        if current.size==(1,1): break
        new_size=(max(1,current.width//2),max(1,current.height//2))
        current=current.resize(new_size,Image.Resampling.LANCZOS)
        if normal_map:
            pixels=np.array(current)
            vectors=pixels[:,:,:3].astype(np.float64)/127.5-1
            vectors/=np.maximum(np.linalg.norm(vectors,axis=2,keepdims=True),1e-12)
            pixels[:,:,:3]=np.clip(np.rint((vectors+1)*127.5),0,255).astype(np.uint8)
            current=Image.fromarray(pixels)
    converted=encode_dxt5(mip_images)
    return converted,dict(name=name,reasons=reasons,source_size=[width,height],
                          output_size=list(target),format='DXT5',mip_levels=len(mip_images),
                          normal_map=normal_map,source_sha256=hashlib.sha256(data).hexdigest(),
                          output_sha256=hashlib.sha256(converted).hexdigest())


def encode_dxt5(mips):
    """Legacy BC3 DDS, including complete block-aligned mip payloads."""
    chunks=[]
    for im in mips:
        buffer=io.BytesIO()
        im.convert('RGBA').save(buffer,format='DDS',pixel_format='DXT5')
        chunks.append(buffer.getvalue())
    header=list(dds_header(chunks[0]))
    header[1] |= 0x20000
    header[6]=len(chunks)
    header[26] |= 0x8|0x400000
    return b'DDS '+struct.pack('<31I',*header)+b''.join(c[128:] for c in chunks)


def save_dxt5(image,path):
    mips=[image.convert('RGBA')]
    while mips[-1].size!=(1,1):
        last=mips[-1]
        mips.append(last.resize((max(1,last.width//2),max(1,last.height//2)),Image.Resampling.LANCZOS))
    path.write_bytes(encode_dxt5(mips))


def as_srgb_dds(data):
    """Declare BC1/2/3 sRGB in a DX10 header without changing compressed pixels."""
    h=list(dds_header(data))
    formats={b'DXT1':72,b'DXT3':75,b'DXT5':78}
    fourcc=data[84:88]
    if fourcc==b'DX10':
        assert struct.unpack_from('<I',data,128)[0] in (72,75,78,99)
        return data
    assert fourcc in formats, ('Unsupported color encoding',fourcc)
    h[19]=4;h[20]=struct.unpack('<I',b'DX10')[0]
    h[21:26]=[0]*5
    return b'DDS '+struct.pack('<31I',*h)+struct.pack('<5I',formats[fourcc],3,0,1,0)+data[128:]


def check_compatible_dds(data):
    """Reject variants that the actual game log identified as unsupported."""
    h=dds_header(data); width,height=h[3],h[2]
    assert width>0 and height>0 and not(width&(width-1)) and not(height&(height-1))
    if h[19]&4:
        assert data[84:88] in (b'DXT1',b'DXT3',b'DXT5',b'DX10'), 'Unsupported DDS FourCC'
        offset=128
        if data[84:88]==b'DX10':
            fmt,dim,misc,arrays,alpha=struct.unpack_from('<5I',data,128)
            assert fmt in (72,75,78) and dim==3 and arrays==1 and misc==0
            block_bytes=8 if fmt==72 else 16;offset=148
        else:block_bytes=8 if data[84:88]==b'DXT1' else 16
        expected=offset+sum(max(1,(max(1,width>>i)+3)//4)*max(1,(max(1,height>>i)+3)//4)*block_bytes
                         for i in range(max(1,h[6])))
        # Original exporters sometimes append padding / undeclared tail mips.
        assert len(data)>=expected, ('DDS compressed mip payload truncated',len(data),expected)
    else:
        assert h[19]&0x40 and h[21]==32, 'BeamNG requires compatible 32-bit RGB DDS here'
        assert h[4]==width*4, 'DDS pitch must be bytes per row'
        assert h[22:26]==(0xff0000,0xff00,0xff,0xff000000)
        assert h[6]==max(width,height).bit_length(), 'Missing mip levels'
        assert len(data)==128+sum(max(1,width>>i)*max(1,height>>i)*4 for i in range(h[6]))
