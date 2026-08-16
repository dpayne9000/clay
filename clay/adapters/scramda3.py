from langchain.prompts.few_shot import FewShotPromptTemplate
from langchain.prompts.prompt import PromptTemplate
from langchain.chat_models import ChatOpenAI
from langchain.schema import HumanMessage
from langchain.chains import LLMChain
import openai
import sys
import os
import json

# This unused adapter connects to Ollama through LangChain.
def fire(prompt, context):
    body = {
        "message": "you are a helpful assistant who manages all aspects of everyday life. ",
        "input": prompt,
    }

    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1")
    OLLAMA_MODEL = prompt.get("model") or os.getenv("OLLAMA_MODEL", "gemma3:4b")
    azureLlm = ChatOpenAI(
        openai_api_base=OLLAMA_BASE_URL,
        openai_api_key="ollama",
        temperature=0.9,
        # max_tokens=1300,
        max_tokens=prompt.get("max_tokens") or 950,
        model_name=OLLAMA_MODEL,
        streaming=False,
    )

    example_prompt = PromptTemplate(
        input_variables=['question','answer'],
        template="Question: {question}\n{answer}"
    )

    examples = [
        {
            'question': ex['question'].replace('{', '{{').replace('}', '}}'),
            'answer':   ex['answer'].replace('{', '{{').replace('}', '}}'),
        }
        for ex in prompt["examples"]
    ]
    template = FewShotPromptTemplate(
        examples=examples,
        example_prompt=example_prompt,
        suffix="Question: {input}",
        input_variables=["input"]
    )

    chain = LLMChain(llm=azureLlm, prompt=template)

    if (len(prompt) > 0):
        # Replace the next line with langchain_visualizer to inspect the chain.
        response = chain.run(prompt["prompt"])
    else:
        # No prompt was provided.
        output = {"statusCode": 501, "body": json.dumps(chain)}


    output = {"statusCode": 200, "body": response}

    return output
