import unittest
from unittest.mock import Mock, patch

from pawzochat.llm.base import LLMResponse
from pawzochat.services.chat import ChatService
from pawzochat.services.message_queue import MessageQueue
from pawzochat.transport.models import Persona


class ChatServiceSilenceTests(unittest.TestCase):
    def test_empty_model_response_produces_no_reply_drafts(self):
        persona = Persona(
            id="ange",
            name="安歌",
            llm_provider="test-provider",
            llm_model="test-model",
        )

        store = Mock()
        store.get_conversation.return_value = {"id": persona.id}
        store.get_recent_rounds.return_value = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "好"}],
            }
        ]

        config = Mock()
        config.get.side_effect = lambda *args, default=None: default
        config.load_personas.return_value = {persona.id: persona}

        provider = Mock()
        provider.chat.return_value = LLMResponse(text="", finish_reason="stop")

        llm_manager = Mock()
        llm_manager.get_model_capabilities.return_value = []
        llm_manager.get_provider.return_value = provider

        service = ChatService(store, config, llm_manager)

        self.assertEqual([], service.process_round(persona.id))

    def test_silent_queue_always_broadcasts_processing_done(self):
        app = Mock()
        app.emoji_service = None
        app.memory_service = None
        app.chat_service.process_round.return_value = []
        app.reply_dispatcher.deliver_messages.return_value = []
        app.conversation_store.add_message.side_effect = (
            lambda persona_id, role, content, source, **kwargs: {
                "role": role,
                "content": content,
                "source": source,
                "timestamp": kwargs.get("timestamp", ""),
            }
        )

        queue = MessageQueue(app)
        queue.enqueue(
            "ange",
            "你好幽默",
            "web",
            reply_ctx={"channel": "web"},
        )

        with patch("pawzochat.services.message_queue.broadcast") as broadcast:
            queue._process("ange")

        events = [call.args[0] for call in broadcast.call_args_list]
        self.assertIn("processing", events)
        self.assertEqual("processing_done", events[-1])




if __name__ == "__main__":
    unittest.main()
