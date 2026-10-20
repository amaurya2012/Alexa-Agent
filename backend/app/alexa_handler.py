# app/alexa_handler.py
import asyncio
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.utils import is_intent_name, is_request_type


class AlexaAgentIntentHandler(AbstractRequestHandler):

  def __init__(self, agent_instance):
    self.agent = agent_instance

  def can_handle(self, handler_input):
    return is_request_type("LaunchRequest")(handler_input) or is_intent_name(
        "AMAZON.FallbackIntent"
    )(handler_input)

  def handle(self, handler_input):
    # User speech extract karein
    request = handler_input.request_envelope.request
    if request.object_type == "LaunchRequest":
      speech = "Home Assistant active hai. Main task, reminder aur inventory me kya madad karoon?"
      return handler_input.response_builder.speak(speech).ask(speech).response

    user_query = request.intent.slots["query"].value  # catch-all slot

    # Agent call karein
    loop = asyncio.get_event_loop()
    chat_result = loop.run_until_complete(
        self.agent.handle_message(user_query)
    )

    # Voice friendly response
    clean_speech = chat_result.response.replace("\n", " ")
    return (
        handler_input.response_builder.speak(clean_speech)
        .ask("Kuch aur karna hai?")
        .response
    )