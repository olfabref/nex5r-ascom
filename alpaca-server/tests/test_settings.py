"""Dashboard settings: camera_url and sensor_type edited from the page, saved to the configuration file
and applied live, refused while a Device is Connected."""
import pytest

from conftest import SERVER_DIR, AlpacaServer
from fake_camera_app import FakeCameraApp
from test_dashboard import action, get, status


@pytest.fixture
def other_camera_app():
    """The same Camera reached at another address (another Wi-Fi network)."""
    app = FakeCameraApp().start()
    yield app
    app.stop()


def config_file(tmp_path):
    return tmp_path / 'test-config.toml'


def test_status_shows_the_editable_settings(alpaca, camera_app):
    assert status(alpaca)['settings'] == {'camera_url': camera_app.url, 'sensor_type': 'color', 'editable': True,
                                          'locked_by': []}


def test_changing_camera_url_talks_to_the_new_address_at_once(alpaca, camera_app, other_camera_app):
    camera_app.stop()
    code, reply = action(alpaca, 'settings', camera_url=other_camera_app.url)
    assert code == 200, reply
    assert reply['ok'] is True and other_camera_app.url in reply['message']
    st = status(alpaca)
    assert st['settings']['camera_url'] == other_camera_app.url
    assert st['camera_app']['reachable'] is True
    assert alpaca.put('camera', 'connected', Connected='true')['ErrorNumber'] == 0
    assert alpaca.put('focuser', 'connected', Connected='true')['ErrorNumber'] == 0
    assert other_camera_app.camera.focus_armed is True


def test_new_camera_url_survives_a_restart_and_the_rest_of_the_file_is_kept(
        camera_app, other_camera_app, start_server, tmp_path):
    alpaca = start_server(camera_app.url)
    camera_app.stop()
    path = config_file(tmp_path)
    # A hand-edited file: its comments must survive the write.
    path.write_text('# my notes\n' + path.read_text().replace(
        "camera_url = '", "# the camera on the home Wi-Fi\ncamera_url = '").replace(
        "sensor_type = 'color'", "sensor_type = 'color'   # or 'mono'"))
    before = path.read_text().splitlines()

    code, reply = action(alpaca, 'settings', camera_url=other_camera_app.url + '/')
    assert code == 200, reply
    after = path.read_text().splitlines()
    assert len(after) == len(before)
    assert [(a, b) for a, b in zip(before, after) if a != b] == [
        (f"camera_url = '{camera_app.url}'", f"camera_url = '{other_camera_app.url}'")]

    alpaca_server = AlpacaServer(path, tmp_path)        # a restart: same file, new process
    try:
        st = status(alpaca_server.client)
        assert st['settings']['camera_url'] == other_camera_app.url
        assert st['camera_app']['reachable'] is True
    finally:
        alpaca_server.stop()


def test_changes_are_refused_while_a_device_is_connected(alpaca, camera_app, other_camera_app, tmp_path):
    before = config_file(tmp_path).read_text()
    assert alpaca.put('focuser', 'connected', Connected='true')['ErrorNumber'] == 0
    assert status(alpaca)['settings']['editable'] is False
    assert status(alpaca)['settings']['locked_by'] == ['Focuser']

    code, reply = action(alpaca, 'settings', camera_url=other_camera_app.url)
    assert code == 409
    assert reply == {'ok': False, 'message': 'Focuser Connected: disconnect it in N.I.N.A. before changing '
                                             'the settings.'}
    assert alpaca.put('camera', 'connected', Connected='true')['ErrorNumber'] == 0
    code, reply = action(alpaca, 'settings', sensor_type='mono')
    assert code == 409 and reply['message'].startswith('Camera and Focuser Connected')

    assert config_file(tmp_path).read_text() == before
    assert status(alpaca)['settings']['camera_url'] == camera_app.url
    assert status(alpaca)['settings']['sensor_type'] == 'color'
    assert alpaca.get('camera', 'sensortype') == 2


def test_sensor_type_applies_to_the_next_exposure(alpaca, tmp_path):
    code, reply = action(alpaca, 'settings', sensor_type='mono')
    assert code == 200, reply
    assert "sensor_type = 'mono'" in config_file(tmp_path).read_text()
    assert alpaca.put('camera', 'connected', Connected='true')['ErrorNumber'] == 0
    assert alpaca.get('camera', 'sensortype') == 0          # monochrome: N.I.N.A. does not debayer
    assert alpaca.put('camera', 'connected', Connected='false')['ErrorNumber'] == 0

    assert action(alpaca, 'settings', sensor_type='color')[0] == 200
    assert alpaca.put('camera', 'connected', Connected='true')['ErrorNumber'] == 0
    assert alpaca.get('camera', 'sensortype') == 2          # RGGB


def test_page_has_a_form_for_the_two_settings_only(alpaca):
    page = get(alpaca, '/')[1].decode('utf-8')
    assert 'id="settings-form"' in page
    assert 'name="camera_url"' in page and 'name="sensor_type"' in page
    assert page.count('<input') == 1 and page.count('<select') == 1
    assert "runAction('settings'" in page


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_saving_the_shipped_config_changes_only_the_two_values(tmp_path, newline):
    import config
    template = (SERVER_DIR / 'config-template.toml').read_text(encoding='utf-8')
    path = tmp_path / 'config.toml'
    path.write_bytes(template.replace('\n', newline).encode('utf-8'))
    config.load(path)

    config.save_device(camera_url='http://10.0.0.7:8080', sensor_type='mono')

    expected = template.replace("camera_url = 'http://192.168.0.23:8080'   #",
                                "camera_url = 'http://10.0.0.7:8080'   #").replace(
                                "sensor_type = 'color'       #", "sensor_type = 'mono'       #")
    assert path.read_bytes() == expected.replace('\n', newline).encode('utf-8')
    assert (config.Config.camera_url, config.Config.sensor_type, config.Config.sensor_mono) == \
        ('http://10.0.0.7:8080', 'mono', True)
    assert list(tmp_path.iterdir()) == [path]                # no temporary file left


@pytest.mark.parametrize('body, why', [
    ({'location': 'Field'}, 'Only camera_url and sensor_type'),
    ({'camera_url': 'http://10.0.0.5:8080', 'port': 1}, 'Only camera_url and sensor_type'),
    ({'camera_url': '192.168.0.23:8080'}, 'is not a camera-app address'),
    ({'camera_url': 'http://192.168.0.23:8080/status'}, 'is not a camera-app address'),
    ({'camera_url': 42}, 'is not a camera-app address'),
    ({'sensor_type': 'rgb'}, "sensor_type must be 'color' or 'mono'"),
    ({}, 'Nothing to change'),
])
def test_other_settings_and_bad_values_are_refused(alpaca, camera_app, tmp_path, body, why):
    before = config_file(tmp_path).read_text()
    code, reply = action(alpaca, 'settings', **body)
    assert code == 409
    assert reply['ok'] is False and why in reply['message']
    assert config_file(tmp_path).read_text() == before
    assert status(alpaca)['settings']['camera_url'] == camera_app.url
