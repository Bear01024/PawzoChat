import sys
import unittest

from pawzochat.mcp.client import _resolve_stdio_command
from pawzochat.transport.qq.models import (
    MSG_TYPE_QUOTE,
    QQInboundMessage,
    normalize_qq_face_markers,
)


class QQFaceMarkerTests(unittest.TestCase):
    def test_decodes_native_face_label(self):
        raw = '<faceType=3,faceId="350",ext="eyJ0ZXh0Ijoi6LS06LS0In0=">'
        self.assertEqual("[QQ表情：贴贴]", normalize_qq_face_markers(raw))

    def test_decodes_face_inside_regular_text(self):
        raw = '给你<faceType=3,faceId="426",ext="eyJ0ZXh0Ijoi546p54GrIn0=">'
        self.assertEqual("给你[QQ表情：玩火]", normalize_qq_face_markers(raw))

    def test_falls_back_to_face_id_when_ext_is_invalid(self):
        raw = '<faceType=3,faceId="350",ext="not-base64">'
        self.assertEqual("[QQ表情 #350]", normalize_qq_face_markers(raw))

    def test_normalizes_message_and_quoted_face(self):
        marker = '<faceType=3,faceId="350",ext="eyJ0ZXh0Ijoi6LS06LS0In0=">'
        message = QQInboundMessage.from_c2c_event({
            "content": marker,
            "message_type": MSG_TYPE_QUOTE,
            "message_scene": {"ext": ["ref_msg_idx=1"]},
            "msg_elements": [{"msg_idx": "1", "content": marker}],
            "author": {"user_openid": "user"},
        })
        self.assertEqual("[QQ表情：贴贴]", message.content)
        self.assertEqual("[QQ表情：贴贴]", message.quote)


class MCPPythonResolutionTests(unittest.TestCase):
    def test_source_python_command_uses_current_interpreter(self):
        self.assertEqual(sys.executable, _resolve_stdio_command("python"))
        self.assertEqual(sys.executable, _resolve_stdio_command("python3"))


if __name__ == "__main__":
    unittest.main()
