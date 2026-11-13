"""Disposable native protection probe. Identity is a test adapter, not SSO acceptance."""
import json, os, re, subprocess, sys, tempfile, time
from pathlib import Path
from uuid import uuid4

ROOT = PKG = None
OWNER='owner@protection.test'

def phase():
    from seaserv import seafile_api as api, ccnet_api
    statefile=ROOT/'state.json'
    local=ROOT/'input'; local.write_bytes(b'protected original content')
    if sys.argv[-1]=='init':
        assert ccnet_api.add_emailuser(OWNER,'!',0,1)==0
        repo=api.create_repo('isolated protection','',OWNER)
        assert api.post_dir(repo,'/','design',OWNER)==0
        assert api.post_file(repo,str(local),'/design','original.prt',OWNER)==0
        old_head=api.get_repo(repo).head_cmmt_id
        local.write_bytes(b'finalized original content')
        assert api.put_file(repo,str(local),'/design','original.prt',OWNER,None)
        statefile.write_text(json.dumps({'repo':repo,'file':api.get_file_id_by_path(repo,'/design/original.prt'),'head':api.get_repo(repo).head_cmmt_id,'old_head':old_head}))
        return
    state=json.loads(statefile.read_text()); repo=state['repo']; checks=[]
    import django
    django.setup()
    from django.conf import settings
    settings.CF_ACL_CACHE_TTL=0
    from cloudfile_ext.v2 import file_protection as p
    from cloudfile_ext.v2.acl_runtime import Authority
    from cloudfile_ext.v2.acl_policy import Principal
    from cloudfile_ext.v2.acl_store import ACLStore
    from django.db import connection, transaction
    from unittest.mock import patch
    from types import SimpleNamespace
    def authority(username):
        return Authority(username,principal=Principal('native-local',username,frozenset()),rules=ACLStore(connection,os.environ['SEAFILE_MYSQL_DB_SEAFILE_DB_NAME'],transaction.atomic),api=api)
    admin=SimpleNamespace(username=OWNER,is_active=True,is_staff=True,admin_permissions=SimpleNamespace(can_manage_library=lambda:True))
    body={'repo_id':repo,'path':'/design/original.prt','expected_file_id':state['file']}
    import jwt, requests, hashlib
    def ticket(mode):
        now=int(time.time())
        return jwt.encode({'uid':'test-owner','sub':OWNER,'repo_id':repo,'path':body['path'],'file_id':state['file'],'mode':mode,'iss':'cloudfile-v2-edit','aud':'cloudfile-edit-agent','iat':now-60,'exp':now+600},os.environ['JWT_PRIVATE_KEY'],algorithm='HS256')
    old_optimistic, old_exclusive, read_ticket = ticket('optimistic-edit'), ticket('exclusive-edit'), ticket('local-view')
    with patch.object(p,'Authority',side_effect=authority):
        response=p._state_change(admin,body,True)
        assert response.status_code==200,response.data
        checks.append('Hub protect with real native file/head and MariaDB audit')
        baseurl='http://127.0.0.1:8082/cf-edit/v1/'
        response=requests.get(baseurl+'read',headers={'Authorization':'Bearer '+read_ticket},timeout=15)
        assert response.status_code==200 and response.content==b'finalized original content',(response.status_code,response.text)
        checks.append('Go scoped read of protected original allowed')
        response=requests.post(baseurl+'checkout',headers={'Authorization':'Bearer '+old_exclusive},json={'base_file_id':state['file'],'terminal_type':'linux','terminal_name':'isolated fixture'},timeout=15)
        assert response.status_code==423 and response.json()['code']=='FILE_PROTECTED',(response.status_code,response.text)
        checks.append('Pre-issued exclusive Agent ticket checkout denied with FILE_PROTECTED')
        content=b'old ticket publish must fail'
        response=requests.post(baseurl+'publish',headers={'Authorization':'Bearer '+old_optimistic,'X-CF-Action':'optimistic','X-CF-Base-ID':state['file'],'X-CF-SHA256':hashlib.sha256(content).hexdigest()},data=content,timeout=15)
        assert response.status_code==423 and response.json()['code']=='FILE_PROTECTED',(response.status_code,response.text)
        checks.append('Pre-issued optimistic Agent ticket full publish denied with FILE_PROTECTED')
        baseline=api.get_repo(repo).head_cmmt_id
        def denied(label,action):
            try:action()
            except Exception:pass
            assert api.get_repo(repo).head_cmmt_id==baseline,label+' changed Branch'
            assert api.get_file_id_by_path(repo,'/design/original.prt')==state['file'],label+' changed original'
            checks.append(label)
        local.write_bytes(b'new content must be rejected')
        denied('C overwrite denied',lambda:api.put_file(repo,str(local),'/design','original.prt',OWNER,None))
        denied('C historical file restore denied',lambda:api.revert_file(repo,state['old_head'],'/design/original.prt',OWNER))
        denied('C historical repo restore denied',lambda:api.revert_repo(repo,state['old_head'],OWNER))
        denied('C original delete denied',lambda:api.del_file(repo,'/design',json.dumps(['original.prt']),OWNER))
        denied('C parent delete denied',lambda:api.del_file(repo,'/',json.dumps(['design']),OWNER))
        denied('C parent rename denied',lambda:api.rename_file(repo,'/','design','renamed',OWNER))
        denied('C original rename denied',lambda:api.rename_file(repo,'/design','original.prt','renamed.prt',OWNER))
        api.copy_file(repo,'/design',json.dumps(['original.prt']),repo,'/design',json.dumps(['copy.prt']),OWNER,0,synchronous=0)
        assert api.get_file_id_by_path(repo,'/design/copy.prt')==state['file']
        copy_head=api.get_repo(repo).head_cmmt_id
        assert api.put_file(repo,str(local),'/design','copy.prt',OWNER,None)
        assert api.get_file_id_by_path(repo,'/design/copy.prt')!=state['file']
        assert p.read_batch(repo,['/design/original.prt','/design/copy.prt'])=={'/design/original.prt':state['file']}
        assert api.revert_file(repo,copy_head,'/design/copy.prt',OWNER)==0
        assert api.get_file_id_by_path(repo,'/design/copy.prt')==state['file']
        assert api.rename_file(repo,'/design','copy.prt','renamed-copy.prt',OWNER)==0
        api.move_file(repo,'/design',json.dumps(['renamed-copy.prt']),repo,'/',json.dumps(['moved-copy.prt']),0,OWNER,0,synchronous=0)
        assert api.get_file_id_by_path(repo,'/moved-copy.prt')==state['file']
        assert api.del_file(repo,'/',json.dumps(['moved-copy.prt']),OWNER)==0
        assert not api.get_file_id_by_path(repo,'/moved-copy.prt')
        assert api.post_dir(repo,'/','unprotected-dir',OWNER)==0
        assert api.rename_file(repo,'/','unprotected-dir','renamed-dir',OWNER)==0
        assert api.del_file(repo,'/',json.dumps(['renamed-dir']),OWNER)==0
        checks.append('C copy editable/restorable/renamable/movable/deletable; unprotected parent operations allowed')
        baseline=api.get_repo(repo).head_cmmt_id
        denied('C original move denied',lambda:api.move_file(repo,'/design',json.dumps(['original.prt']),repo,'/',json.dumps(['moved.prt']),0,OWNER,0,synchronous=0))
        # Entire repo deletion is blocked by configured scope, even after unprotect.
        try:api.remove_repo(repo)
        except Exception:pass
        assert api.get_repo(repo) is not None
        checks.append('C whole repo delete denied')
        response=p._state_change(admin,body,False); assert response.status_code==200,response.data
        response=requests.post(baseurl+'publish',headers={'Authorization':'Bearer '+old_optimistic,'X-CF-Action':'optimistic','X-CF-Base-ID':state['file'],'X-CF-SHA256':hashlib.sha256(content).hexdigest()},data=content,timeout=15)
        assert response.status_code==200,(response.status_code,response.text)
        checks.append('Same optimistic ticket publishes successfully after unprotect')
        assert api.put_file(repo,str(local),'/design','original.prt',OWNER,None)
        checks.append('Hub unprotect restores native write')
    print(json.dumps({'passed':checks,'identity':'test native-local principal/admin; not Etech/SSO'},indent=2))

def run():
    if not __debug__:
        raise SystemExit('Do not disable probe assertions with python -O')
    global ROOT, PKG
    if os.environ.get('CF_TEST_FILE_PROTECTION') != '1':
        raise SystemExit('Requires CF_TEST_FILE_PROTECTION=1 and a disposable db host; never use a deployed database')
    PKG = Path(os.environ['CF_NATIVE_TEST_PACKAGE'])
    if len(sys.argv) > 1:
        if sys.argv[-1] not in ('init', 'test'):
            raise SystemExit('unknown probe phase')
        ROOT = Path(os.environ['CF_NATIVE_TEST_ROOT'])
    else:
        ROOT = Path(tempfile.mkdtemp(prefix='cf-protection-native-'))
        os.environ['CF_NATIVE_TEST_ROOT'] = str(ROOT)
    if len(sys.argv)>1:
        phase(); return

    import pymysql
    admin=pymysql.connect(host='db',user='root',password='isolated-protection-test',autocommit=True,charset='utf8mb4')
    schemas={k:'protection_native_'+uuid4().hex for k in ('account','files')}
    process=None
    go_process=None
    try:
        with admin.cursor() as c:
            for kind,name in schemas.items():
                c.execute('CREATE DATABASE '+name); c.execute('USE '+name)
                for statement in re.findall(r'CREATE TABLE[\s\S]+?;', (PKG/'sql/mysql'/('ccnet.sql' if kind=='account' else 'seafile.sql')).read_text()):c.execute(statement)
        from cloudfile_ext.v2.schema import FreshSchema
        admin.select_db(schemas['files']); sql=PKG/'sql/mysql'
        FreshSchema(admin,(sql/'cloudfile-v2.sql').read_text(),edit_ddl=(sql/'cloudfile-v2-edit.sql').read_text(),audit_ddl=(sql/'cloudfile-v2-audit.sql').read_text(),protection_ddl=(sql/'cloudfile-v2-protection.sql').read_text()).install()
        for name in ('conf','data','ccnet'): (ROOT/name).mkdir(parents=True,exist_ok=True)
        config=f'''[database]
    type=mysql
    host=db
    user=root
    password=isolated-protection-test
    db_name={schemas['files']}
    ccnet_db_name={schemas['account']}
    connection_charset=utf8mb4
    [fileserver]
    use_go_fileserver=true
    port=8082
    [cloudfile]
    '''
        (ROOT/'conf/seafile.conf').write_text(config)
        os.environ.update(SEAFILE_DATA_DIR=str(ROOT/'data'),SEAFILE_CENTRAL_CONF_DIR=str(ROOT/'conf'),SEAHUB_LOG_DIR=str(ROOT),SEAFILE_MYSQL_DB_HOST='db',SEAFILE_MYSQL_DB_USER='root',SEAFILE_MYSQL_DB_PASSWORD='isolated-protection-test',SEAFILE_MYSQL_DB_CCNET_DB_NAME=schemas['account'],SEAFILE_MYSQL_DB_SEAFILE_DB_NAME=schemas['files'],SEAFILE_MYSQL_DB_SEAHUB_DB_NAME=schemas['files'],DJANGO_SETTINGS_MODULE='seahub.settings',JWT_PRIVATE_KEY='isolated-native-protection-key-1234567890')
        def start():
            nonlocal process
            process=subprocess.Popen([str(PKG/'seafile/bin/seaf-server'),'-F',str(ROOT/'conf'),'-c',str(ROOT/'ccnet'),'-d',str(ROOT/'data'),'-l',str(ROOT/'native.log'),'-f'],stdout=(ROOT/'stderr').open('a'),stderr=subprocess.STDOUT)
            for _ in range(200):
                if process.poll() is not None:raise RuntimeError((ROOT/'stderr').read_text()+(ROOT/'native.log').read_text())
                if (ROOT/'data/seafile.sock').exists():time.sleep(.2);return
                time.sleep(.05)
            raise RuntimeError('native socket readiness timeout')
        start(); subprocess.run([sys.executable,__file__,'init'],check=True)
        process.terminate();process.wait(timeout=10)
        state=json.loads((ROOT/'state.json').read_text()); (ROOT/'conf/seafile.conf').write_text(config+'protection_repo_ids = '+state['repo']+'\ncheckout_enabled = true\ncheckout_repo_ids = '+state['repo']+'\n')
        start()
        go_process=subprocess.Popen([str(PKG/'seafile/bin/fileserver'),'-F',str(ROOT/'conf'),'-d',str(ROOT/'data'),'-l',str(ROOT/'go.log')],stdout=(ROOT/'go.stderr').open('w'),stderr=subprocess.STDOUT)
        import requests
        for _ in range(200):
            if go_process.poll() is not None:raise RuntimeError((ROOT/'go.stderr').read_text()+(ROOT/'go.log').read_text())
            try:
                if requests.get('http://127.0.0.1:8082/protocol-version',timeout=1).status_code==200:break
            except requests.RequestException:pass
            time.sleep(.05)
        else:raise RuntimeError('Go readiness timeout')
        subprocess.run([sys.executable,__file__,'test'],check=True)
    finally:
        if go_process is not None and go_process.poll() is None:go_process.terminate();go_process.wait(timeout=10)
        if process is not None and process.poll() is None:process.terminate();process.wait(timeout=10)
        with admin.cursor() as c:
            for name in schemas.values():c.execute('DROP DATABASE IF EXISTS '+name)
        admin.close()


if __name__ == '__main__':
    run()
