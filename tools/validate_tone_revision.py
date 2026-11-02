"""R5 texture/compositing and isolated Lua exposure lifecycle checks."""
import json
import sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).parent/'lib'))
from PIL import Image
import numpy as np
from lupa.luajit21 import LuaRuntime
from validation_images import open_texture

base=Path(__file__).resolve().parents[1]
unpacked=base/'output/unpacked'
level=unpacked/'levels/st_stctk_ac_port'
materials=json.loads((level/'main.materials.json').read_text())
def pixels(path):return np.array(open_texture(unpacked/path.lstrip('/')).convert('RGBA'))
summary={'revision':5,'result':'PASS','game_launched':False,'road_mean_rgb':{},'skids':{}}
for name,mat in materials.items():
    if name.endswith(('_roadmain','_surfaceroad')):
        rgb=pixels(mat['Stages'][0]['baseColorMap'])
        mean=rgb[:,:,:3].mean(0).mean(0)
        assert 40<mean.mean()<70 and rgb[:,:,3].min()==255
        summary['road_mean_rgb'][name]=mean.tolist()
    if name.startswith('acst_st_stcgrooverad_'):
        assert mat['translucent'] and not mat['alphaTest'] and not mat['translucentZWrite']
        assert mat['translucentBlendOp']=='LerpAlpha' and not mat['castShadows']
        stage=mat['Stages'][0];rgba=pixels(stage['baseColorMap'])
        alpha=pixels(stage['opacityMap'])[:,:,0].astype(float)/255
        assert alpha.min()==0 and 0<alpha.max()<1
        assert np.count_nonzero((alpha>0)&(alpha<1))>1000
        assert rgba[:,:,:3].max()<40
        # Conventional source-alpha blending must leave zero-coverage background
        # unchanged and must only darken asphalt, never add a gray rectangle.
        background=np.array([52.,52.,54.])
        blended=rgba[:,:,:3]*alpha[:,:,None]+background*(1-alpha[:,:,None])
        assert np.array_equal(blended[alpha==0],np.broadcast_to(background,blended[alpha==0].shape))
        assert (blended<=background+1e-8).all()
        summary['skids'][name]={'alpha_min':float(alpha.min()),'alpha_max':float(alpha.max()),
                               'zero_alpha_pixels':int((alpha==0).sum()),'blend_only_darkens':True}
assert len(summary['road_mean_rgb'])==2 and len(summary['skids'])==2

source=(level/'mainLevel.lua').read_text()
def setup(value=0.4,present=True):
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.execute('effect={exposureBiasEV=0.4}; present=true; scenetree={findObject=function(name) if present then return effect end end}')
    lua.globals().effect.exposureBiasEV=value;lua.globals().present=present
    return lua,lua.execute(source)
lua,m=setup();m.onClientStartMission()
assert abs(lua.globals().effect.exposureBiasEV-.2)<1e-9
for _ in range(100):m.onUpdate()
assert abs(lua.globals().effect.exposureBiasEV-.2)<1e-9
m.onClientEndMission();m.onExtensionUnloaded();m.onUpdate()
assert abs(lua.globals().effect.exposureBiasEV-.4)<1e-9
lua,m=setup(present=False);m.onClientStartMission();m.onUpdate()
lua.globals().present=True;m.onUpdate()
assert abs(lua.globals().effect.exposureBiasEV-.2)<1e-9
lua.globals().effect.exposureBiasEV=.7;m.onClientEndMission()
assert lua.globals().effect.exposureBiasEV==.7
lua,m=setup();m.onUpdate();m.onExtensionUnloaded()
assert abs(lua.globals().effect.exposureBiasEV-.4)<1e-9
lua,m=setup();m.onUpdate();lua.globals().present=False;m.onClientEndMission()
lua,m=setup(value='invalid');m.onUpdate();m.onClientEndMission()
summary['exposure_luajit_checks']=['minus_0.20_EV','no_per_frame_accumulation','restore_on_exit',
    'restore_on_unload','late_HDR_initialization','preserve_manual_changes','missing_effect','invalid_value']
(base/'output/tone_validation.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
