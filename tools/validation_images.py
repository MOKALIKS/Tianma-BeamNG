"""Decode BC sRGB payloads with Pillow versions lacking DXGI 72/75/78 support.

Only the in-memory decoder header changes; disk textures retain explicit sRGB.
Returned pixels are encoded sRGB values, not linear-light values.
"""
import io
import struct
from pathlib import Path
from PIL import Image


def open_texture(path):
    data=Path(path).read_bytes()
    if data[:4]==b'DDS ' and data[84:88]==b'DX10':
        fmt,dim,misc,arrays,alpha=struct.unpack_from('<5I',data,128)
        codes={72:b'DXT1',75:b'DXT3',78:b'DXT5'}
        if fmt in codes:
            assert dim==3 and misc==0 and arrays==1
            header=bytearray(data[:128]);header[84:88]=codes[fmt]
            data=bytes(header)+data[148:]
    return Image.open(io.BytesIO(data))
