import unittest
from unittest.mock import Mock

from pawzochat.llm.base import LLMResponse
from pawzochat.services.chat import ChatService
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


if __name__ == "__main__":
    unittest.main()
