"""Install only the already verified map. Never starts or controls the game."""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode=True
from package_mod import install_mod, sha256, require_game_closed

base=Path(__file__).resolve().parents[1]
archive=base/'output/st_stctk_ac_port.zip'
mod_directory=Path(sys.argv[1]).resolve()
validation=json.loads((base/'output/offline_validation.json').read_text(encoding='utf-8'))
assert validation['result']=='PASS' and validation['zip_sha256']==sha256(archive), 'Archive must pass current offline validation'
log_path=mod_directory.parents[1]/'beamng.log'
log_offset=log_path.stat().st_size if log_path.exists() else 0
result=install_mod(archive, mod_directory, base/'work/backups')
# Invalidate only this mod's old database record while the game is stopped.
# On next launch it is rediscovered and mounted from its current directory index.
require_game_closed()
db_path=mod_directory.parent/'db.json'
if db_path.exists():
    db=json.loads(db_path.read_text(encoding='utf-8'))
    mod_key=archive.stem.lower()
    record=db.get('mods',{}).get(mod_key)
    if record:
        if Path(record.get('filename','')).name.lower()!=archive.name.lower():
            raise RuntimeError('Mod database record does not match installed archive')
        backup=base/'work/backups'/('mods_db_'+sha256(db_path)[:16]+'.json.bak')
        if not backup.exists():
            backup.write_bytes(db_path.read_bytes())
        del db['mods'][mod_key]
        stage=db_path.with_suffix('.json.pending')
        stage.write_text(json.dumps(db,ensure_ascii=False,indent=2),encoding='utf-8')
        require_game_closed()
        stage.replace(db_path)
        result.update(mod_db_backup=str(backup),mod_db_invalidated_record=mod_key,
                      other_mod_records_changed=False)
result.update(log_path=str(log_path),log_offset_before_install=log_offset)
(base/'output/installation_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
