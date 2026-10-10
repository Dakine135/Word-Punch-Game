from word_punch.vision.camera_select import CameraInfo, choose, rank

# What this laptop reports through DirectShow.
LAPTOP = [
    CameraInfo(0, "Integrated Camera", 700, True),
    CameraInfo(1, "EOS Webcam Utility", 700, False),
    CameraInfo(2, "Logi C270 HD WebCam", 700, True),
    CameraInfo(3, "Camera (NVIDIA Broadcast)", 700, False),
    CameraInfo(4, "EOS Webcam Utility Pro", 700, False),
]


def test_usb_webcam_beats_built_in():
    assert choose(LAPTOP).name == "Logi C270 HD WebCam"


def test_built_in_when_no_usb_webcam():
    cams = [c for c in LAPTOP if "C270" not in c.name]
    assert choose(cams).name == "Integrated Camera"


def test_virtual_cameras_never_auto_picked():
    assert choose([c for c in LAPTOP if not c.has_hw_id]) is None
    assert rank(CameraInfo(0, "OBS Virtual Camera", 700, False)) is None


def test_name_preference_wins():
    assert choose(LAPTOP, prefer_name="integrated").name == "Integrated Camera"


def test_pi_codec_nodes_skipped():
    cams = [CameraInfo(10, "bcm2835-codec-decode", 200, False),
            CameraInfo(0, "UVC Camera (046d:0825)", 200, False)]
    assert choose(cams).index == 0
