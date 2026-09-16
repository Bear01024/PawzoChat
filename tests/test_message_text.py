import unittest

from pawzochat.utils.message_text import clean_assistant_reply_text


class CleanAssistantReplyTextTests(unittest.TestCase):
    def test_replaces_silent_markers_with_smiling_emoji(self):
        for marker in ("（已静默）", "(已静默)", "【已静默】", "[已静默]", "已静默"):
            with self.subTest(marker=marker):
                self.assertEqual("😊", clean_assistant_reply_text(marker))

    def test_replaces_silent_marker_inside_reply(self):
        self.assertEqual(
            "😊稍后见",
            clean_assistant_reply_text("（已静默）稍后见"),
        )


if __name__ == "__main__":
    unittest.main()
