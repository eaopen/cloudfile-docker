"""Native path-birth + real SQL metadata probe, not an identity/HTTP gate."""
import os
import sys
import tempfile
from unittest.mock import Mock


def run(repo):
    package = '/opt/seafile/seafile-server-latest'
    os.chdir(package + '/seahub')
    sys.path[:0] = [package + '/seahub', package + '/seahub/thirdpart',
                   package + '/seafile/lib/python3/site-packages']
    os.environ.update(SEAFILE_CENTRAL_CONF_DIR='/shared/seafile/conf',
        SEAFILE_RPC_PIPE_PATH=package + '/runtime', SEAFILE_DATA_DIR='/shared/seafile/seafile-data')
    import pymysql
    from seaserv import seafile_api
    from cloudfile_extensions.resources.native import NativeResourceReader
    from cloudfile_extensions.resources.store import ResourceStore
    from cloudfile_extensions.authorization.read import ContentMetadataWriteAuthority
    from cloudfile_extensions.schema.runner import SchemaRunner
    from cloudfile_extensions.common.errors import ContractError
    db = pymysql.connect(host='db', user=os.environ['SEAFILE_MYSQL_DB_USER'],
        password=os.environ['SEAFILE_MYSQL_DB_PASSWORD'], database='seafile_db', autocommit=True)
    try:
        SchemaRunner(db).apply()
        reader = NativeResourceReader(seafile_api)
        ref = dict(repo_id=repo, path='/annotations-probe.prt', kind='file')
        owner = 'admin@smoke.invalid'
        store = ResourceStore(db, inspector=Mock(), write_guard=Mock(),
            secret=b'isolated-runtime-fixture-secret-32-bytes', mutation_hook=Mock())
        # Authorization itself already has separate runtime evidence. This
        # fixture isolates the new native reader and actual metadata transaction.
        authority = Mock(spec=ContentMetadataWriteAuthority)
        authority.actor = 'fixture-user'; authority.state = Mock(connection=db, provider='fixture-directory')
        authority.effective_access = dict(read=True, write=True)
        def consume(reference, callback):
            db.begin()
            try:
                with db.cursor() as cursor:
                    result = callback(cursor, reference)
                db.commit()
                return result
            finally:
                db.rollback()
        authority.consume.side_effect = consume
        def snapshot():
            return store.resolve_authorized(ref, authority=authority, lifecycle_reader=reader, include_tags=True)
        with tempfile.NamedTemporaryFile() as temporary:
            temporary.write(b'original native file'); temporary.flush()
            seafile_api.post_file(repo, temporary.name, '/', 'annotations-probe.prt', owner)
            initial = snapshot()
            assert initial['uid'] is None
            saved, _ = store.write_authorized(ref, dict(description='eTech drawing', local_open_type='UG12'),
                expected_revision=initial['revision'], authority=authority, lifecycle_reader=reader, idempotency_key='attributes-1')
            tagged, _ = store.replace_user_tags_authorized(ref, [], expected_revision=saved['revision'],
                authority=authority, lifecycle_reader=reader, request_id='native-fixture',
                tag_values=[dict(label='drawing')], idempotency_key='tags-1')
            temporary.seek(0); temporary.truncate(); temporary.write(b'edited file'); temporary.flush()
            seafile_api.put_file(repo, temporary.name, '/', 'annotations-probe.prt', owner, None)
            after = snapshot()
            assert all(after[key] == value for key, value in tagged.items())
            assert after['description'] == 'eTech drawing' and after['local_open_type'] == 'UG12'
            assert after['tags'][0]['label'] == 'drawing'
            seafile_api.del_file(repo, '/', '["annotations-probe.prt"]', owner)
            seafile_api.post_file(repo, temporary.name, '/', 'annotations-probe.prt', owner)
            try:
                snapshot()
            except ContractError as error:
                assert error.code == 'PATH_STATE_PENDING'
            else:
                raise AssertionError('recreated native object reused old annotations')
        return dict(result='passed', checks=['sparse_read', 'description_open_type_and_user_tag_save',
            'native_replace_preserves_annotations', 'native_recreate_rejects_old_state'],
            scope='Actual CE14 RPC/commit history + SQL; authorization mocked; not HTTP or release acceptance')
    finally:
        db.close()


if __name__ == '__main__':
    import json
    try:
        print(json.dumps(run(sys.argv[1])))
    except Exception as error:
        import traceback
        print(json.dumps(dict(result='failed', error_type=type(error).__name__,
            code=getattr(error, 'code', None),
            location=[(os.path.basename(frame.filename), frame.lineno)
                for frame in traceback.extract_tb(error.__traceback__)[-3:]])))
