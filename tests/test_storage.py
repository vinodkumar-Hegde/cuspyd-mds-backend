"""Offline SDK contract and deployment configuration tests; no AWS calls."""
from pathlib import Path

from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber
from pydantic import ValidationError
import pytest

from app import storage
from app.config import Settings, settings


def test_s3_key_prefix_content_metadata_and_kms(monkeypatch, tmp_path):
    cfg = settings()
    for field, value in {'storage_backend':'s3', 's3_bucket':'test-media-bucket',
                         's3_prefix':'production/images', 's3_kms_key_id':'test-kms-key',
                         'upload_dir':tmp_path, 's3_region':'ap-south-1'}.items():
        monkeypatch.setattr(cfg, field, value)
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'test-only-key')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'test-only-secret')
    client = storage.s3_client.__wrapped__()
    monkeypatch.setattr(storage, 's3_client', lambda: client)
    with Stubber(client) as stub:
        stub.add_response('put_object', {}, {
            'Bucket':'test-media-bucket', 'Key':'production/images/file.png',
            'Body':b'validated-content', 'ContentType':'image/png',
            'Metadata':{'category':'question-images'},
            'ServerSideEncryption':'aws:kms', 'SSEKMSKeyId':'test-kms-key',
        })
        storage.save_image('file.png', b'validated-content', 'image/png', 'question-images')
        stub.assert_no_pending_responses()
    assert not list(tmp_path.iterdir())


def test_s3_network_outage_is_an_operational_error(monkeypatch):
    monkeypatch.setattr(settings(), 'storage_backend', 's3')
    def unreachable():
        raise EndpointConnectionError(endpoint_url='https://unreachable.invalid')
    monkeypatch.setattr(storage, 's3_client', unreachable)
    with pytest.raises(storage.StorageUnavailable):
        storage.save_image('file.png', b'content', 'image/png', 'syndromes')


@pytest.mark.parametrize('overrides', [
    {'storage_backend':'unknown'},
    {'storage_backend':'s3', 's3_bucket':''},
    {'storage_backend':'s3', 's3_bucket':'test-media-bucket'},
    {'storage_backend':'s3', 's3_bucket':'NOT_A_BUCKET', 's3_region':'ap-south-1'},
    {'s3_prefix':'../outside'},
    {'s3_presign_seconds':7200},
])
def test_storage_misconfiguration_is_rejected(overrides):
    base = {'database_url':'postgresql+psycopg://test:test@db/mdslate_test',
            'jwt_secret':'configuration-test-secret-over-32-characters',
            'aws_region':'', 'aws_default_region':'', 's3_region':'', 's3_bucket':''}
    with pytest.raises(ValidationError):
        Settings(**(base | overrides))


def test_storage_region_can_differ_from_ses_and_prefix_is_normalized():
    base = {'database_url':'postgresql+psycopg://test:test@db/mdslate_test',
            'jwt_secret':'configuration-test-secret-over-32-characters',
            'storage_backend':'s3', 's3_bucket':'test-media-bucket',
            'aws_region':'ap-south-1', 's3_region':'eu-west-1', 's3_prefix':'/production/images/'}
    cfg = Settings(**base)
    assert cfg.storage_region == 'eu-west-1'
    assert cfg.s3_prefix == 'production/images'
    assert Settings(**(base | {'s3_region':''})).storage_region == 'ap-south-1'


def test_local_writes_are_atomic_and_do_not_use_aws(monkeypatch, tmp_path):
    monkeypatch.setattr(settings(), 'storage_backend', 'local')
    monkeypatch.setattr(settings(), 'upload_dir', tmp_path)
    def unexpected_aws_call():
        raise AssertionError('Local mode must not construct an AWS client')
    monkeypatch.setattr(storage, 's3_client', unexpected_aws_call)
    storage.save_image('file.png', b'content', 'image/png', 'syndromes')
    assert (tmp_path / 'file.png').read_bytes() == b'content'
    assert list(tmp_path.iterdir()) == [Path(tmp_path / 'file.png')]
