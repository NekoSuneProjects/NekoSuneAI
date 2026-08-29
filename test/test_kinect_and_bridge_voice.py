from pathlib import Path


def test_bridge_emma_patch_defaults_to_edge_voice():
    text = Path('nekosuneai/bridge_edge_voice_patch.py').read_text(encoding='utf-8')
    assert 'en-US-EmmaMultilingualNeural' in text
    assert 'config.bridge_tts_engine = "edge-stream"' in text
    assert 'bridge_voice._stream_route_unavailable = lambda _error: False' in text


def test_kinect_patch_uses_libfreenect_and_local_expression_context():
    text = Path('nekosuneai/kinect_vision_patch.py').read_text(encoding='utf-8')
    assert 'freenect_sync_get_video' in text
    assert 'LocalAffectDetector' in text
    assert 'posture' in text
    assert 'gesture' in text
    assert 'kinect_vision_enabled' in text


def test_docker_installs_kinect_runtime_and_opencv():
    text = Path('Dockerfile').read_text(encoding='utf-8')
    assert 'libfreenect0.5' in text
    assert 'opencv-python-headless' in text
