import hashlib,os,sqlite3,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parent.parent
python=str(root/'.venv/bin/python')
env={**os.environ,'DB_PATH':str(root/'demo.sqlite3'),'MEDIA_ROOT':str(root/'demo-media')}
with tempfile.TemporaryDirectory() as tmp:
    archive=subprocess.check_output([python,'manage.py','backup_data','--output',tmp],env=env,cwd=root,text=True).strip()
    dest=Path(tmp)/'restored'
    subprocess.run([python,'scripts/restore_backup.py',archive,str(dest)],cwd=root,check=True)
    with sqlite3.connect(root/'demo.sqlite3') as original,sqlite3.connect(dest/'db.sqlite3') as restored:
        for table in ['registry_dataset','registry_column','registry_check','registry_attachment','registry_submission','registry_audit','auth_user']:
            a=original.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
            b=restored.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
            assert a==b,table
        assert restored.execute('SELECT COUNT(*) FROM registry_attachment').fetchone()[0]>0
    for path in (root/'demo-media').rglob('*'):
        if path.is_file():
            restored_path=dest/'media'/path.relative_to(root/'demo-media')
            assert hashlib.sha256(path.read_bytes()).digest()==hashlib.sha256(restored_path.read_bytes()).digest()
    result=subprocess.run([python,'manage.py','check'],env={**env,'DB_PATH':str(dest/'db.sqlite3'),'MEDIA_ROOT':str(dest/'media')},cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    print('PASS: backup/restore DB tables, exact submission bytes, attachment hashes, restored application system check.')
