from datetime import timedelta
from io import BytesIO

import pytest
from PIL import Image, PngImagePlugin
from sqlalchemy import func, select

from app.maintenance import backup, cleanup, restore
from app.models import AvatarImage, User, now_utc


def picture(format='PNG', color='red', size=(300, 180)):
    image = Image.new('RGB', size, color)
    buffer = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('Comment', 'private source metadata')
    image.save(buffer, format=format, **({'pnginfo': metadata} if format == 'PNG' else {}))
    return buffer.getvalue()


@pytest.mark.parametrize('format', ['PNG', 'JPEG', 'WEBP'])
def test_upload_is_persistent_private_normalized_png_without_metadata(h, format):
    h.register()
    headers = h.login()
    response = h.client.put('/api/v1/account/avatar', content=picture(format), headers=headers)
    assert response.status_code == 200, response.text
    account = response.json()['account']
    assert len(account['avatar']) <= 24 and account['avatar'].startswith('upload_')
    url = account['avatarUrl']
    retrieved = h.client.get(url)
    assert retrieved.status_code == 200 and retrieved.headers['content-type'] == 'image/png'
    assert retrieved.headers['cache-control'] == 'no-store'
    with Image.open(BytesIO(retrieved.content)) as result:
        assert result.size == (256, 256) and result.format == 'PNG'
        assert not result.info
    assert h.client.get('/api/v1/auth/me').json()['account']['avatarUrl'] == url
    assert h.client.patch('/api/v1/account/profile', json={'name': 'changed'}, headers=headers).json()['account']['avatarUrl'] == url
    h.client.post('/api/v1/auth/logout', headers=headers)
    assert h.client.get(url).status_code == 401
    h.login()
    assert h.client.get(url).content == retrieved.content
    h.register('another-avatar@example.org')
    h.login('another-avatar@example.org')
    assert h.client.get(url).status_code == 404


@pytest.mark.parametrize('content,code', [
    (b'', 'AVATAR_EMPTY'), (b'not an image', 'AVATAR_INVALID'),
    (b'<svg xmlns="http://www.w3.org/2000/svg"/>', 'AVATAR_INVALID'),
    (b'x' * (2 * 1024 * 1024 + 1), 'AVATAR_TOO_LARGE'),
], ids=['empty', 'invalid', 'svg', 'oversize'])
def test_invalid_upload_keeps_existing_avatar(h, content, code):
    h.register()
    headers = h.login()
    original = h.client.put('/api/v1/account/avatar', content=picture(), headers=headers).json()['account']
    response = h.client.put('/api/v1/account/avatar', content=content, headers=headers)
    assert response.json()['error']['code'] == code
    assert h.client.get('/api/v1/auth/me').json()['account']['avatarUrl'] == original['avatarUrl']


def test_animated_or_oversized_images_are_rejected(h):
    h.register()
    headers = h.login()
    buffer = BytesIO()
    Image.new('RGB', (8, 8), 'red').save(buffer, 'WEBP', save_all=True, append_images=[Image.new('RGB', (8, 8), 'blue')], duration=100)
    assert h.client.put('/api/v1/account/avatar', content=buffer.getvalue(), headers=headers).json()['error']['code'] == 'AVATAR_ANIMATED'
    assert h.client.put('/api/v1/account/avatar', content=picture(size=(10001, 1)), headers=headers).json()['error']['code'] == 'AVATAR_DIMENSIONS'


def test_replacement_and_presets_remove_old_image(h):
    h.register()
    headers = h.login()
    first = h.client.put('/api/v1/account/avatar', content=picture(), headers=headers).json()['account']
    second = h.client.put('/api/v1/account/avatar', content=picture(color='blue'), headers=headers).json()['account']
    assert first['avatarUrl'] != second['avatarUrl'] and h.client.get(first['avatarUrl']).status_code == 404
    with h.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(AvatarImage)) == 1
    response = h.client.patch('/api/v1/account/profile', json={'avatar': 'leaf'}, headers=headers)
    assert response.json()['account']['avatar'] == 'leaf' and response.json()['account']['avatarUrl'] is None
    assert h.client.get(second['avatarUrl']).status_code == 404
    with h.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(AvatarImage)) == 0


def test_auth_csrf_and_administrator_limits(h):
    assert h.client.put('/api/v1/account/avatar', content=picture()).status_code == 401
    h.register()
    h.login()
    assert h.client.put('/api/v1/account/avatar', content=picture()).status_code == 403
    h.make_admin()
    headers = h.login('admin@example.org')
    assert h.client.put('/api/v1/account/avatar', content=picture(), headers=headers).status_code == 403


def test_avatar_is_in_business_backup_and_purged_after_closure(h, tmp_path):
    user = h.register()
    headers = h.login()
    url = h.client.put('/api/v1/account/avatar', content=picture(), headers=headers).json()['account']['avatarUrl']
    data = h.client.get(url).content
    settings = h.app.state.settings.model_copy(update={'backup_directory': tmp_path / 'backups'})
    engine = h.app.state.engine
    saved = backup(engine, settings)
    assert saved['tables']['avatar_images'] == 1
    h.client.patch('/api/v1/account/profile', json={'avatar': 'default'}, headers=headers)
    restore(engine, settings, saved['path'], confirmed_database=str(engine.url.database))
    headers = h.login()
    assert h.client.get(url).content == data
    assert h.client.post('/api/v1/account/close', json={'email': 'candidate@example.org', 'confirmed': True}, headers=headers).status_code == 200
    with h.app.state.session_factory() as db:
        at = db.get(User, user['id']).closed_at + timedelta(days=30)
    cleanup(engine, settings, at=at)
    with h.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(AvatarImage)) == 0
        assert db.get(User, user['id']).purged_at <= now_utc() + timedelta(days=31)
